#!/usr/bin/env bash
MAIN_DEVICE=alsa_output.usb-Corsair_CORSAIR_VIRTUOSO_XT_Wireless_Gaming_Receiver_16356807000600fc-00.analog-stereo

sleep 1

pactl load-module module-null-sink media.class=Audio/Sink sink_name="SystemIn" device.description='"System In"' channel_map=stereo
pactl load-module module-null-sink media.class=Audio/Sink sink_name="MusicIn" device.description='"Music In"' channel_map=stereo
pactl load-module module-null-sink media.class=Audio/Sink sink_name="VoiceIn" device.description='"Voice In"' channel_map=stereo
pactl load-module module-null-sink media.class=Audio/Sink sink_name="BrowserIn" device.description='"Browser In"' channel_map=stereo
pactl load-module module-null-sink media.class=Audio/Sink sink_name="GameIn" device.description='"Game In"' channel_map=stereo
pactl load-module module-null-sink media.class=Audio/Source/Virtual sink_name="MixOut" device.description='"Mix Out"' channel_map=front-left,front-right

sleep 1

pw-link SystemIn:monitor_FL MixOut:input_FL
pw-link SystemIn:monitor_FR MixOut:input_FR
pw-link MusicIn:monitor_FL MixOut:input_FL
pw-link MusicIn:monitor_FR MixOut:input_FR
pw-link VoiceIn:monitor_FL MixOut:input_FL
pw-link VoiceIn:monitor_FR MixOut:input_FR
pw-link BrowserIn:monitor_FL MixOut:input_FL
pw-link BrowserIn:monitor_FR MixOut:input_FR
pw-link GameIn:monitor_FL MixOut:input_FL
pw-link GameIn:monitor_FR MixOut:input_FR

pw-link MixOut:capture_FL $MAIN_DEVICE:playback_FL
pw-link MixOut:capture_FR $MAIN_DEVICE:playback_FR
