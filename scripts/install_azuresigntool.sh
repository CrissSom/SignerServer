#!/usr/bin/env bash
# Install AzureSignTool on a Debian/Ubuntu host (no Docker).
# Run as root or with sudo.
set -euo pipefail

DOTNET_VERSION="8.0"

echo "==> Installing .NET SDK ${DOTNET_VERSION}..."
wget -q https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb -O /tmp/ms.deb
dpkg -i /tmp/ms.deb
rm /tmp/ms.deb
apt-get update -qq
apt-get install -y --no-install-recommends dotnet-sdk-${DOTNET_VERSION}

echo "==> Installing AzureSignTool..."
dotnet tool install --global AzureSignTool

TOOL_PATH="${HOME}/.dotnet/tools"
if ! echo "${PATH}" | grep -q "${TOOL_PATH}"; then
    echo "export PATH=\"\${PATH}:${TOOL_PATH}\"" >> "${HOME}/.bashrc"
    export PATH="${PATH}:${TOOL_PATH}"
fi

echo "==> AzureSignTool version: $(AzureSignTool --version)"
echo "Done. Add '${TOOL_PATH}' to PATH permanently if needed."
