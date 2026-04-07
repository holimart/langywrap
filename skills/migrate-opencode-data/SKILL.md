---
name: migrate-opencode-data
description: Migrate OpenCode data directory (logs, configs, database) to a custom location using symlinks
license: MIT
compatibility: opencode
metadata:
  audience: users
  purpose: configuration
---

## What I do

This skill migrates the OpenCode data directory from its default location (`~/.local/share/opencode/`) to a custom directory of your choice. It works by:

1. Moving all OpenCode data (logs, database, storage, snapshots) to the target directory
2. Creating a symlink from the default location to the new location

## When to use me

Use this when you want to:
- Store OpenCode data in a different partition or drive
- Keep OpenCode data in a location that's easier to back up
- Organize your data storage differently

## Usage

1. Ask the user for the target directory path where they want to store OpenCode data
2. Use the `/migrate-opencode-data` skill with the target path

## Migration Steps

### Step 1: Get target directory

Ask the user: "Where would you like to store OpenCode data? (e.g., /path/to/custom/directory)"

### Step 2: Verify OpenCode is not running

Before migration, ensure OpenCode is not running. Check for running processes:
```bash
pgrep -f opencode || echo "No opencode processes running"
```

If running processes exist, ask the user to close them.

### Step 3: Create target directory and migrate

Execute these commands:

```bash
# Define paths
SOURCE_DIR="$HOME/.local/share/opencode"
TARGET_DIR="<USER_SPECIFIED_TARGET>"

# Create target directory if it doesn't exist
mkdir -p "$TARGET_DIR"

# Move all content from source to target
cp -a "$SOURCE_DIR/." "$TARGET_DIR/"

# Remove the original directory
rm -rf "$SOURCE_DIR"

# Create symlink from default location to new location
ln -s "$TARGET_DIR" "$SOURCE_DIR"

# Verify the symlink was created correctly
ls -la "$SOURCE_DIR"
```

### Step 4: Verify migration

Check that the symlink works:
```bash
ls -la ~/.local/share/opencode
# Should show something like: opencode -> /path/to/custom/directory
```

Check that data is accessible:
```bash
ls ~/.local/share/opencode/
# Should list: auth.json, log/, opencode.db, storage/, etc.
```

## Important Notes

1. **Backup first**: Always recommend backing up before migration
2. **Close OpenCode**: Ensure OpenCode is fully closed before migrating
3. **Permissions**: The target directory should be owned by the same user
4. **Space**: Ensure the target location has enough disk space
5. **After migration**: OpenCode will automatically use the new location via the symlink

## Rollback (if needed)

To revert to the original location:
```bash
# Remove the symlink
rm ~/.local/share/opencode

# Move data back
mv /path/to/custom/directory/* ~/.local/share/opencode/

# Remove the now-empty custom directory
rmdir /path/to/custom/directory
```