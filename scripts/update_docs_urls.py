import sys
import os
import re

def main():
    print(f"Current Working Directory: {os.getcwd()}")
    
    if len(sys.argv) < 2:
        print("Error: Missing target_backend_domain argument")
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

    print(f"Target Backend Domain: {target_backend_domain}")
    print(f"Target Frontend Domain: {target_frontend_domain}")
    
    # Files to update
    files = [
        "frontend/public/docs/api.json",
        "frontend/public/docs/socket.json",
        "frontend/public/docs/skill.md",
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
        print(f"Processing: {file_path}")
        
        if not os.path.exists(file_path):
            print(f"ERROR: File not found: {file_path}")
            continue
            
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            new_content = content
            
            # --- 1. Backend Domain Replacement ---
            
            # Replace wss://<backend_domain>
            for domain in known_backend_domains:
                pattern = f"wss://{domain}"
                target = f"wss://{target_backend_domain}"
                if pattern in new_content:
                    new_content = new_content.replace(pattern, target)
                    print(f"  Replaced {pattern} -> {target}")

            # Replace https://<backend_domain>
            for domain in known_backend_domains:
                pattern = f"https://{domain}"
                target = f"https://{target_backend_domain}"
                if pattern in new_content:
                    new_content = new_content.replace(pattern, target)
                    print(f"  Replaced {pattern} -> {target}")
            
            # Replace bare backend domains in text if strictly matching known backend domains
            # (Be careful not to replace frontend domains here)
            for domain in known_backend_domains:
                if domain in new_content and domain != target_backend_domain:
                    # We need to be careful. If we have "api-dev.clawarena.io" and we want "api.clawarena.io", 
                    # replacing it is fine.
                    # But we should ensure we are not replacing it inside a URL we already replaced?
                    # Actually, if we already replaced the URL, the domain string won't be there anymore (it's now target_domain).
                    # So this handles text occurrences like "Connect to api-dev.clawarena.io..."
                    new_content = new_content.replace(domain, target_backend_domain)
                    print(f"  Replaced text {domain} -> {target_backend_domain}")

            # --- 2. Frontend Domain Replacement ---
            
            # Replace https://<frontend_domain>
            for domain in known_frontend_domains:
                pattern = f"https://{domain}"
                target = f"https://{target_frontend_domain}"
                # We need to avoid replacing something that was already correct or part of a backend URL 
                # (though backend URLs start with api-, so they shouldn't match known_frontend_domains usually).
                # Exception: "clawarena.io" is a substring of "api.clawarena.io".
                # So "https://clawarena.io" is a substring of "https://api.clawarena.io".
                # If we replace "https://clawarena.io" with "https://dev.clawarena.io", 
                # then "https://api.clawarena.io" becomes "https://api.dev.clawarena.io" ?? NO.
                # "https://api.clawarena.io" does NOT contain "https://clawarena.io". 
                # It contains "https://api...".
                # But if we search for just "clawarena.io" text, that would be dangerous.
                # So strictly replacing "https://{domain}" is safer.
                
                if pattern in new_content and pattern != target:
                     new_content = new_content.replace(pattern, target)
                     print(f"  Replaced {pattern} -> {target}")

            # --- 3. Relative API Path Replacement (Markdown only) ---
            
            if file_path.endswith('.md'):
                # Regex to match "/api/" that is NOT preceded by "http://" or "https://" or "wss://" or a domain char
                # We use a negative lookbehind to ensure we don't match something that is already a full URL.
                # Also, we must be careful not to match if it's already replaced in this run.
                # However, since we replace with "https://{target}/api/", the next time it won't match 
                # because it will be preceded by "https://...".
                # But wait, "https://target/api/" contains "/api/".
                # The negative lookbehind (?<!https:) should prevent matching "https://.../api/".
                # Let's verify: "https://domain.com/api/" -> preceded by "m", not "https:".
                # Ah! The lookbehind (?<!https:) only checks the immediate characters.
                # "https://domain.com/api/" -> the characters before "/api/" are "m", "o", "c", ...
                # So (?<!https:) will pass (because "om" != "https:").
                # This is why we need to check for "://" or similar.
                
                # Better approach: Match "/api/" but ensure it's not part of a full URL.
                # A full URL starts with http://, https://, or wss://
                # So if we see "/api/", we check if it has "://" somewhere before it on the same line? 
                # No, that's too complex for regex lookbehind.
                
                # Simple heuristic:
                # If it starts with "/" (e.g. "/api/..."), it's relative.
                # If it starts with " " or "(" or start of line, it's relative.
                # We want to catch:
                # "POST /api/register"
                # "(/api/register)"
                # "`/api/register`"
                
                # We do NOT want to catch:
                # "https://domain.com/api/register"
                
                # So we look for "/api/" preceded by whitespace, start of line, '(', '"', or '`'.
                # OR, simpler: not preceded by a domain character (letter, digit, dot, dash).
                # Because in a URL, it would be "domain.com/api/". The char before "/" is "m".
                # In a relative path, it's " /api/" (space) or "^/api/" (start).
                
                # So: (?<![a-zA-Z0-9.-])/api/
                # This means: "/api/" not preceded by alphanumeric, dot, or dash.
                # This covers "domain.com/api/" (preceded by m) -> blocked.
                # Covers "/api/" (preceded by nothing or space) -> matched.
                
                pattern_rel = r'(?<![a-zA-Z0-9.-])/api/'
                
                if re.search(pattern_rel, new_content):
                    # We only want to replace if we are sure it is intended as an API path.
                    # But /api/ is pretty specific in our context.
                    new_content = re.sub(pattern_rel, f"https://{target_backend_domain}/api/", new_content)
                    print(f"  Replaced relative paths /api/ -> https://{target_backend_domain}/api/")

            if new_content != content:
                with open(file_path, 'w') as f:
                    f.write(new_content)
                print(f"  Updated successfully.")
                success_count += 1
            else:
                print(f"  No changes needed.")
                
        except Exception as e:
            print(f"ERROR updating {file_path}: {e}")
            # We don't exit here to allow other files to be processed, 
            # but usually we might want to fail the build. 
            # For now, let's just print error.
            sys.exit(1)

    print(f"Done. Updated {success_count} files.")

if __name__ == "__main__":
    main()
