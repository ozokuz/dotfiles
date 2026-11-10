if [ -f "$HOME/.bashrc" ]; then
    . "$HOME/.bashrc"
fi
if [ -f "$HOME/.config/envstore/login.sh" ]; then
    . "$HOME/.config/envstore/login.sh"
fi
