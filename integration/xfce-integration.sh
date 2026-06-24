#!/bin/bash
#===============================================================================
# XFCE Panel Integration for Network Recovery Tool
# Generic version - works on any XFCE panel configuration
#===============================================================================

echo "🔧 Setting up Network Recovery panel integration..."

# Check if XFCE panel is running
if ! pgrep -x "xfce4-panel" > /dev/null; then
    echo "⚠️  XFCE panel not running - integration will apply on next login"
fi

# Ensure desktop file exists
if [[ ! -f /usr/share/applications/network-recover.desktop ]]; then
    echo "❌ Desktop file not found. Run the installer first."
    exit 1
fi

# Copy to user's local applications
mkdir -p ~/.local/share/applications
cp /usr/share/applications/network-recover.desktop ~/.local/share/applications/

# Try to add launcher to the panel
if command -v xfconf-query &>/dev/null; then
    echo "📌 Adding launcher to XFCE panel..."
    
    # Detect ALL panels
    PANELS=$(xfconf-query -c xfce4-panel -p /panels -l 2>/dev/null | grep -E '^/panels/panel-[0-9]+$' | sed 's|/panels/||')
    
    if [[ -z "$PANELS" ]]; then
        echo "⚠️  No XFCE panels detected"
    else
        # Find which panel has the systray (network icon)
        TARGET_PANEL=""
        SYSTRAY_PLUGIN=""
        SYSTRAY_POS=""
        PLUGIN_LIST=""
        
        for panel in $PANELS; do
            PLUGIN_LIST=$(xfconf-query -c xfce4-panel -p /panels/$panel/plugin-ids 2>/dev/null | tr -d '[]' | tr -d ' ')
            
            if [[ -n "$PLUGIN_LIST" ]]; then
                IFS=',' read -ra PLUGINS <<< "$PLUGIN_LIST"
                
                # Check if any plugin in this panel is a systray or statusnotifier
                for plugin_id in "${PLUGINS[@]}"; do
                    PLUGIN_TYPE=$(xfconf-query -c xfce4-panel -p /plugins/plugin-$plugin_id/type 2>/dev/null)
                    
                    if [[ "$PLUGIN_TYPE" == "systray" ]] || [[ "$PLUGIN_TYPE" == "statusnotifier" ]]; then
                        TARGET_PANEL="$panel"
                        SYSTRAY_PLUGIN="$plugin_id"
                        # Find position
                        for i in "${!PLUGINS[@]}"; do
                            if [[ "${PLUGINS[$i]}" == "$plugin_id" ]]; then
                                SYSTRAY_POS=$i
                                break
                            fi
                        done
                        break 2
                    fi
                done
            fi
        done
        
        if [[ -z "$TARGET_PANEL" ]]; then
            echo "⚠️  No systray/statusnotifier plugin found (network icon not detected)"
            echo "   The launcher will be added to the first panel instead."
            
            # Fallback: use first panel
            TARGET_PANEL=$(echo "$PANELS" | head -1)
            PLUGIN_LIST=$(xfconf-query -c xfce4-panel -p /panels/$TARGET_PANEL/plugin-ids 2>/dev/null | tr -d '[]' | tr -d ' ')
            SYSTRAY_POS=-1  # Add to end
        fi
        
        # Find next available plugin ID
        if [[ -n "$PLUGIN_LIST" ]]; then
            IFS=',' read -ra PLUGINS <<< "$PLUGIN_LIST"
            NEXT_ID=$(printf "%s\n" "${PLUGINS[@]}" | sort -n | tail -1)
            NEXT_ID=$((NEXT_ID + 1))
        else
            NEXT_ID=1
        fi
        
        # Create new launcher plugin
        xfconf-query -c xfce4-panel -p /plugins/plugin-$NEXT_ID -n -t string -s "launcher" 2>/dev/null || true
        xfconf-query -c xfce4-panel -p /plugins/plugin-$NEXT_ID/items -n -t string -s "network-recover.desktop" 2>/dev/null || true
        
        # Build new plugin list with launcher inserted after systray
        if [[ -n "$PLUGIN_LIST" ]]; then
            IFS=',' read -ra PLUGINS <<< "$PLUGIN_LIST"
            NEW_LIST=""
            
            if [[ "$SYSTRAY_POS" -ge 0 ]]; then
                # Insert after systray
                for i in "${!PLUGINS[@]}"; do
                    NEW_LIST="${NEW_LIST}${PLUGINS[$i]},"
                    if [[ $i -eq $SYSTRAY_POS ]]; then
                        NEW_LIST="${NEW_LIST}${NEXT_ID},"
                    fi
                done
            else
                # Add to end
                for i in "${!PLUGINS[@]}"; do
                    NEW_LIST="${NEW_LIST}${PLUGINS[$i]},"
                done
                NEW_LIST="${NEW_LIST}${NEXT_ID},"
            fi
            
            # Remove trailing comma and wrap in brackets
            NEW_LIST="[${NEW_LIST%,}]"
            
            # Apply new plugin order
            xfconf-query -c xfce4-panel -p /panels/$TARGET_PANEL/plugin-ids -s "$NEW_LIST" 2>/dev/null || true
            
            if [[ "$SYSTRAY_POS" -ge 0 ]]; then
                echo "✅ Launcher added to panel $TARGET_PANEL (plugin $NEXT_ID) next to network icon"
            else
                echo "✅ Launcher added to panel $TARGET_PANEL (plugin $NEXT_ID)"
            fi
        else
            echo "⚠️  Could not determine plugin list"
        fi
    fi
    
    # If automated addition failed, show manual instructions
    if [[ -z "$TARGET_PANEL" ]] || [[ -z "$NEXT_ID" ]]; then
        echo ""
        echo "   To add manually:"
        echo "   1. Right-click panel → Panel → Panel Preferences"
        echo "   2. Click 'Items' tab"
        echo "   3. Click '+' Add"
        echo "   4. Search for 'Network Diagnose & Repair'"
        echo "   5. Click 'Add'"
        echo "   6. Drag it next to the network icon (usually in Status Tray)"
        echo ""
    fi
else
    echo "⚠️  xfconf-query not found - cannot auto-configure panel"
    echo ""
    echo "   Please add the launcher manually:"
    echo "   1. Right-click panel → Panel → Panel Preferences"
    echo "   2. Click 'Items' tab"
    echo "   3. Click '+' Add"
    echo "   4. Search for 'Network Diagnose & Repair'"
    echo "   5. Click 'Add'"
    echo "   6. Drag it next to the network icon"
    echo ""
fi

# Restart panel to apply changes
if pgrep -x "xfce4-panel" > /dev/null; then
    echo "🔄 Restarting XFCE panel..."
    xfce4-panel -r 2>/dev/null || pkill -USR1 xfce4-panel 2>/dev/null || true
    echo "✅ Panel restarted"
fi

echo ""
echo "=========================================="
echo "  PANEL INTEGRATION COMPLETE"
echo "=========================================="
echo ""
echo "  Your icon should now appear next to"
echo "  the network icon in your panel."
echo ""
echo "  If not, add it manually using the"
echo "  instructions above."
echo ""