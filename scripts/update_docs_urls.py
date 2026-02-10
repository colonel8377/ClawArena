import sys
import os

def update_file(file_path, target_domain):
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        
        # We are replacing the base domain "clawarena.io" with the target domain.
        # This assumes the source files strictly use "clawarena.io" as the placeholder/base.
        # Examples:
        # "https://clawarena.io" -> "https://api-dev.clawarena.io"
        # "wss://clawarena.io" -> "wss://api-dev.clawarena.io"
        
        # To avoid double replacement if the target domain contains the source domain (e.g. api.clawarena.io contains clawarena.io),
        # we should be careful. But since this runs on fresh source code in CI, simple replacement is acceptable 
        # as long as the source strictly uses "clawarena.io" and not "api.clawarena.io".
        
        new_content = content.replace("clawarena.io", target_domain)
        
        with open(file_path, 'w') as f:
            f.write(new_content)
        print(f"Updated {file_path} with domain {target_domain}")
    except Exception as e:
        print(f"Error updating {file_path}: {e}")

def main():
    if len(sys.argv) < 2:
        print("Usage: python update_docs_urls.py <target_domain>")
        sys.exit(1)
    
    target_domain = sys.argv[1]
    
    # Files to update
    files = [
        "frontend/public/docs/skill.json",
        "frontend/public/docs/skill.md",
        "frontend/public/docs/skills/texas.md",
        "frontend/public/docs/skills/werewolf.md"
    ]
    
    base_dir = os.getcwd()
    
    for relative_path in files:
        file_path = os.path.join(base_dir, relative_path)
        if os.path.exists(file_path):
            update_file(file_path, target_domain)
        else:
            print(f"Warning: File not found: {file_path}")

if __name__ == "__main__":
    main()
