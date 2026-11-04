#!/bin/sh
#Check if this is a Yocto image
if [ -d /home/root ]; then
# Define the expected OpenSSL version
cd /home/pi/src
./fixpi4ssl.sh
source /etc/profile
sleep 2
EXPECTED_OPENSSL_VERSION="1.1.1u"
FILE="/etc/profile.d/yocto_extra_packages.sh"
LINE_TO_CHECK='export LD_LIBRARY_PATH="/usr/local/lib/openssl/openssl/openssl/lib:$LD_LIBRARY_PATH"'
NEW_LINE='export LD_LIBRARY_PATH="/usr/local/lib/openssl/openssl/lib:$LD_LIBRARY_PATH"'

# Check if the file exists
if [ -f "$FILE" ]; then
    # Check if the line exists in the file
    if grep -qF "$LINE_TO_CHECK" "$FILE"; then
        # Replace the line
        sed -i "s|$LINE_TO_CHECK|$NEW_LINE|" "$FILE"
        echo "Line replaced in $FILE"
    else
        echo "Line not found in $FILE"
    fi
else
    echo "Error: File $FILE not found."
fi
# Function to check if a command is available
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Get the installed OpenSSL version
INSTALLED_OPENSSL_VERSION=$(openssl version | awk '{print $2}')

# Compare the installed version with the expected version
if [ "$INSTALLED_OPENSSL_VERSION" == "$EXPECTED_OPENSSL_VERSION" ]; then
    echo "Correct: OpenSSL version $EXPECTED_OPENSSL_VERSION is installed."
else
    echo "Not Correct: Installed OpenSSL version is $INSTALLED_OPENSSL_VERSION, expected version $EXPECTED_OPENSSL_VERSION."
   cd /home/pi/src
    ./updatepi4.sh
fi
fi

# Ensure libaries are correctly linked

library_path="/usr/local/lib/openssl/openssl/lib"
init_script="/etc/init.d/powertune"

# Check if the library path is already present in the init script
if grep -q "$library_path" "$init_script"; then
    echo "Library path already present in $init_script."
else
    # If not present, add the library path to the top of the file
    echo "Adding library path to $init_script."
    sed -i "1iexport LD_LIBRARY_PATH=\"$library_path:\$LD_LIBRARY_PATH\"" "$init_script"
fi

echo "Disable System Logs"
cd /home/pi/src
./fixlog.sh
echo "Install fonts"
cd /home/pi/src/fonts
sudo cp *.* /usr/local/share/fonts
echo "Check Nohup"
cd /home/pi/src
./fixnohup.sh

echo "Skipping legacy proprietary ECU daemon updates in this fork"
