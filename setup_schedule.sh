#!/bin/bash
# Sets up a daily launchd job to run the newsletter every morning at 7:00 AM.
# Usage: bash setup_schedule.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_NAME="com.dailynewsletter.run"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
PYTHON_PATH="$(which python3)"
NEWSLETTER_SCRIPT="${SCRIPT_DIR}/src/newsletter.py"
LOG_FILE="${SCRIPT_DIR}/newsletter.log"

echo "Setting up daily newsletter schedule..."
echo "  Python:     $PYTHON_PATH"
echo "  Script:     $NEWSLETTER_SCRIPT"
echo "  Log file:   $LOG_FILE"
echo "  Schedule:   Every day at 7:00 AM"

cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_PATH}</string>
        <string>${NEWSLETTER_SCRIPT}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${SCRIPT_DIR}</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>7</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>${LOG_FILE}</string>
    <key>StandardErrorPath</key>
    <string>${LOG_FILE}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
EOF

launchctl unload "$PLIST_PATH" 2>/dev/null
launchctl load "$PLIST_PATH"

echo ""
echo "Done! Newsletter scheduled daily at 7:00 AM."
echo ""
echo "Commands:"
echo "  Test now:    python3 ${NEWSLETTER_SCRIPT}"
echo "  View logs:   tail -f ${LOG_FILE}"
echo "  Unschedule:  launchctl unload ${PLIST_PATH}"
