import sys
import os

def main():
    print(f"Current Working Directory: {os.getcwd()}")
    
    if len(sys.argv) < 2:
        print("Error: Missing target_domain argument")
        sys.exit(1)
    
    target_domain = sys.argv[1]
    print(f"Target Domain: {target_domain}")
    
    # Files to update
    files = [
        "frontend/public/docs/skill.json",
        "frontend/public/docs/skill.md",
        "frontend/public/docs/skills/texas.md",
        "frontend/public/docs/skills/werewolf.md"
    ]
    
    base_dir = os.getcwd()
    success_count = 0
    
    for relative_path in files:
        file_path = os.path.join(base_dir, relative_path)
        print(f"Processing: {file_path}")
        
        if not os.path.exists(file_path):
            print(f"ERROR: File not found: {file_path}")
            # List directory to debug
            dir_name = os.path.dirname(file_path)
            if os.path.exists(dir_name):
                print(f"Contents of {dir_name}:")
                print(os.listdir(dir_name))
            else:
                print(f"Directory {dir_name} does not exist either.")
            sys.exit(1)
            
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            new_content = content
            
            # List of domains to replace
            # We treat all of these as "placeholders" and replace them with the target_domain.
            # This ensures that if the file was committed with a dev or prod URL, it gets updated correctly.
            # NOTE: We primarily target wss:// and https:// prefixes to avoid breaking non-URL text,
            # but we also handle specific bare domains if needed.
            
            known_domains = [
                "api.clawarena.io",
                "api-dev.clawarena.io",
                "api-pre.clawarena.io",
                "clawarena.io"
            ]
            
            # 1. Replace wss://<domain> -> wss://<target_domain>
            for domain in known_domains:
                pattern = f"wss://{domain}"
                target = f"wss://{target_domain}"
                if pattern in new_content:
                    new_content = new_content.replace(pattern, target)
                    print(f"  Replaced {pattern} -> {target}")

            # 2. Replace https://<domain> -> https://<target_domain>
            for domain in known_domains:
                pattern = f"https://{domain}"
                target = f"https://{target_domain}"
                if pattern in new_content:
                    new_content = new_content.replace(pattern, target)
                    print(f"  Replaced {pattern} -> {target}")

            # 3. Special case for description or other text mentions: "on api.clawarena.io"
            # We only replace "api.clawarena.io" or "api-dev.clawarena.io" etc. in text IF it matches our known backends.
            # We must be careful not to replace "clawarena.io" if it refers to the frontend website.
            # But "api.clawarena.io" is definitely backend.
            
            backend_domains_text = [d for d in known_domains if d.startswith("api")]
            for domain in backend_domains_text:
                 if domain in new_content and domain != target_domain:
                     new_content = new_content.replace(domain, target_domain)
                     print(f"  Replaced text {domain} -> {target_domain}")

            # 4. Handle relative paths in Markdown files
            # If the file is a markdown file, we want to replace relative API paths with absolute paths.
            # e.g. "POST /api/register" -> "POST https://{target_domain}/api/register"
            # But we must avoid double replacement if it's already absolute.
            
            if file_path.endswith('.md'):
                import re
                
                # Regex to match "/api/" that is NOT preceded by "http://" or "https://" or "wss://"
                # Negative lookbehind is perfect for this.
                # (?<!://) checks that "://" is not immediately before "/api/"
                # But python re requires fixed width lookbehind? No, "://" is fixed width.
                # Wait, we might have "clawarena.io/api/", so we should check for that too?
                # Actually, simply looking for space or start of line followed by /api/ is safer?
                # Or just use the negative lookbehind for protocol.
                
                # Pattern: replace "/api/" with "https://{target_domain}/api/"
                # BUT only if not preceded by http(s)://domain
                
                def replace_relative_api(match):
                    return f"https://{target_domain}/api/"
                
                # Pattern: Any "/api/" that is NOT part of a full URL.
                # A full URL would be http://.../api/ or https://.../api/
                # So we look for "/api/" that is NOT preceded by a non-whitespace character?
                # No, that might exclude markdown links like [text](/api/...).
                
                # Let's use a robust approach:
                # Find all occurrences of "/api/"
                # Check context for each.
                
                # Using regex with negative lookbehind for '://' (protocol) and '.' (domain chars before slash)
                # If we have "clawarena.io/api/", we probably don't want to break it if it's already correct,
                # OR we might want to rewrite it.
                # But let's assume relative paths start with /api/.
                
                # (?<!https:)(?<!http:)(?<!wss:)(?<!\.)/api/
                # This says: not preceded by https:, http:, wss:, or a dot (domain).
                # This should catch "/api/" in "POST /api/..." or "(/api/...)"
                
                pattern_rel = r'(?<!https:)(?<!http:)(?<!wss:)(?<!\.)/api/'
                
                if re.search(pattern_rel, new_content):
                    new_content = re.sub(pattern_rel, f"https://{target_domain}/api/", new_content)
                    print(f"  Replaced relative paths /api/ -> https://{target_domain}/api/")

            if new_content != content:
                with open(file_path, 'w') as f:
                    f.write(new_content)
                print(f"  Updated successfully.")
                
                # Verify content
                with open(file_path, 'r') as f:
                    saved_content = f.read()
                    print(f"  First 500 chars after update:\n{saved_content[:500]}")
                    
                success_count += 1
            else:
                print(f"  No changes needed (or patterns not found).")
                
        except Exception as e:
            print(f"ERROR updating {file_path}: {e}")
            sys.exit(1)

    print(f"Done. Updated {success_count} files.")

if __name__ == "__main__":
    main()
