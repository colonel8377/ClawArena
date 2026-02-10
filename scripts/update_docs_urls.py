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
            
            # Check if replacement is needed
            if "clawarena.io" in content:
                # Perform replacement
                # IMPORTANT: Simple replacement might be risky if target_domain contains source string.
                # e.g. replacing "clawarena.io" with "api-dev.clawarena.io"
                # "wss://clawarena.io" -> "wss://api-dev.clawarena.io" (Correct)
                # But if run twice: "wss://api-dev.clawarena.io" -> "wss://api-dev.api-dev.clawarena.io" (Wrong)
                # However, in CI, this runs once on fresh checkout, so it is safe.
                
                new_content = content.replace("clawarena.io", target_domain)
                
                # Check if wss was updated
                if "wss://clawarena.io" in content and f"wss://{target_domain}" in new_content:
                    print(f"  Verified: wss://clawarena.io -> wss://{target_domain}")
                
                with open(file_path, 'w') as f:
                    f.write(new_content)
                print(f"  Updated successfully.")
                success_count += 1
            else:
                print(f"  No 'clawarena.io' found to replace.")
                
        except Exception as e:
            print(f"ERROR updating {file_path}: {e}")
            sys.exit(1)

    print(f"Done. Updated {success_count} files.")

if __name__ == "__main__":
    main()
