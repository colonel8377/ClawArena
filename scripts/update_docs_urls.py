import sys
import os
import re

import logging

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

def main():
    log.info(f"Current Working Directory: {os.getcwd()}")
    
    if len(sys.argv) < 2:
        log.error("Error: Missing target_backend_domain argument")
        sys.exit(1)
    
    target_backend_domain = sys.argv[1]
    
    # If a second argument is provided, use it as the target frontend domain.
    # Otherwise, try to infer it or default to a safe guess.
    if len(sys.argv) >= 3:
        target_frontend_domain = sys.argv[2]
    else:
        # Simple inference based on standard naming convention
        if "api-dev" in target_backend_domain:
            target_frontend_domain = "dev.clawarena.io"
        elif "api-pre" in target_backend_domain:
            target_frontend_domain = "pre.clawarena.io"
        elif "api.clawarena.io" in target_backend_domain:
            target_frontend_domain = "clawarena.io"
        else:
            # Fallback: just use the backend domain (unlikely to be correct for frontend links but better than crashing)
            target_frontend_domain = target_backend_domain

    log.info(f"Target Backend Domain: {target_backend_domain}")
    log.info(f"Target Frontend Domain: {target_frontend_domain}")
    
    # Files to update
    files = [
        "frontend/public/docs/api.json",
        "frontend/public/docs/socket.json",
        "frontend/public/docs/skill.md",
        "frontend/public/docs/heartbeat.md",
        "frontend/public/docs/messaging.md",
        "frontend/public/docs/skills/texas.md",
        "frontend/public/docs/skills/werewolf.md"
    ]
    
    base_dir = os.getcwd()
    success_count = 0
    
    known_backend_domains = [
        "api.clawarena.io",
        "api-dev.clawarena.io",
        "api-pre.clawarena.io"
    ]

    known_frontend_domains = [
        "clawarena.io",
        "dev.clawarena.io",
        "pre.clawarena.io"
    ]
    
    for relative_path in files:
        file_path = os.path.join(base_dir, relative_path)
        log.info(f"Processing: {file_path}")
        
        if not os.path.exists(file_path):
            log.error(f"ERROR: File not found: {file_path}")
            continue
            
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            new_content = content

            if "<host>" in new_content:
                new_content = new_content.replace("https://<host>", f"https://{target_backend_domain}")
                # Also replace bare <host> if it exists (though usually it's part of a URL)
                new_content = new_content.replace("<host>", target_backend_domain)
                log.info(f"  Replaced <host> -> {target_backend_domain}")

            # --- 1. Backend Domain Replacement ---
            for domain in known_backend_domains:
                pattern = f"wss://{domain}"
                target = f"wss://{target_backend_domain}"
                if pattern in new_content:
                    new_content = new_content.replace(pattern, target)
                    log.info(f"  Replaced {pattern} -> {target}")

            # Replace https://<backend_domain>
            for domain in known_backend_domains:
                pattern = f"https://{domain}"
                target = f"https://{target_backend_domain}"
                if pattern in new_content:
                    new_content = new_content.replace(pattern, target)
                    log.info(f"  Replaced {pattern} -> {target}")
            
            # Replace bare backend domains in text if strictly matching known backend domains
            # (Be careful not to replace frontend domains here)
            for domain in known_backend_domains:
                if domain in new_content and domain != target_backend_domain:
                    new_content = new_content.replace(domain, target_backend_domain)
                    log.info(f"  Replaced text {domain} -> {target_backend_domain}")

            # --- 2. Frontend Domain Replacement ---
            
            # Replace https://<frontend_domain>
            for domain in known_frontend_domains:
                pattern = f"https://{domain}"
                target = f"https://{target_frontend_domain}"

                if pattern in new_content and pattern != target:
                     new_content = new_content.replace(pattern, target)
                     log.info(f"  Replaced {pattern} -> {target}")

            # --- 3. Relative API Path Replacement (Markdown only) ---
            
            if file_path.endswith('.md'):
                pattern_rel = r'(?<![a-zA-Z0-9.-])/api/'
                
                if re.search(pattern_rel, new_content):
                    new_content = re.sub(pattern_rel, f"https://{target_backend_domain}/api/", new_content)
                    log.info(f"  Replaced relative paths /api/ -> https://{target_backend_domain}/api/")

            if new_content != content:
                with open(file_path, 'w') as f:
                    f.write(new_content)
                log.info(f"  Updated successfully.")
                success_count += 1
            else:
                log.info(f"  No changes needed.")
                
        except Exception as e:
            log.error(f"ERROR updating {file_path}: {e}")
            sys.exit(1)

    log.info(f"Done. Updated {success_count} files.")

if __name__ == "__main__":
    main()
