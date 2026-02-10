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
            
            # Use 'clawarena.io' as the placeholder base domain
            # If target_domain is 'api-dev.clawarena.io', we replace 'clawarena.io' with it.
            # But wait! If the text is 'api.clawarena.io', replacing 'clawarena.io' -> 'api-dev.clawarena.io'
            # results in 'api.api-dev.clawarena.io'. This is BAD.
            
            # Correct logic:
            # We want to replace SPECIFIC occurrences.
            # 1. "wss://clawarena.io" -> "wss://<target>"
            # 2. "https://clawarena.io" -> "https://<target>"
            # 3. "api.clawarena.io" -> "<target>" (Maybe?)
            
            # To be safe, we should replace specific URL patterns.
            
            new_content = content
            
            # Replace wss://clawarena.io
            if "wss://clawarena.io" in new_content:
                new_content = new_content.replace("wss://clawarena.io", f"wss://{target_domain}")
                print(f"  Replaced wss://clawarena.io -> wss://{target_domain}")

            # Replace https://clawarena.io
            if "https://clawarena.io" in new_content:
                new_content = new_content.replace("https://clawarena.io", f"https://{target_domain}")
                print(f"  Replaced https://clawarena.io -> https://{target_domain}")

            # Also handle api.clawarena.io if it exists (for Prod mentions)
            # If the file mentions 'api.clawarena.io' and we are deploying to dev, we might want to change it too?
            # Or maybe the source file ONLY contains 'clawarena.io' as per my rewrite.
            # Let's check skill.json content I wrote earlier.
            # "api_base": "wss://clawarena.io",
            # "http_base": "https://clawarena.io"
            # So the specific replacements above should cover it.
            
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
