# Zinit
ZINIT_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}/zinit/zinit.git"
[ ! -d $ZINIT_HOME ] && mkdir -p "$(dirname $ZINIT_HOME)"
[ ! -d $ZINIT_HOME/.git ] && git clone https://github.com/zdharma-continuum/zinit.git "$ZINIT_HOME"
source "${ZINIT_HOME}/zinit.zsh"

# Plugins
zinit light zsh-users/zsh-syntax-highlighting
zinit light zsh-users/zsh-completions
zinit light zsh-users/zsh-autosuggestions
zinit light Aloxaf/fzf-tab

# Snippets
zinit snippet OMZL::git.zsh
zinit snippet OMZP::git
zinit snippet OMZP::sudo
zinit snippet OMZP::archlinux

# Load completions
autoload -Uz compinit && compinit

zinit cdreplay -q

# Completion Styling
zstyle ':completion:*' menu no
zstyle ':completion:*' matcher-list 'm:{a-z}={A-Z}'     # Case-insensitive matching
zstyle ':completion:*' list-colors ${(s.:.)LS_COLORS}   # Colored completions
zstyle ':fzf-tab:complete:cd:*' fzf-preview 'eza -1 --color=always $realpath'
#zstyle ':completion:*' group-name ''                     # Group completions
#zstyle ':completion:*:descriptions' format '%F{yellow}-- %d --%f'
#zstyle ':completion:*:warnings' format '%F{red}-- no matches --%f'

# Keybindings
bindkey -e                                        # Emacs bindings mode
backward-kill-slash-separated() {
  local WORDCHARS=${WORDCHARS//\/}
  zle backward-kill-word
}
zle -N backward-kill-slash-separated
bindkey '^p' history-search-backward              # Ctrl+P
bindkey '^n' history-search-forward               # Ctrl+N
bindkey '^[[1;5C' forward-word                    # Ctrl+Right
bindkey '^[[1;5D' backward-word                   # Ctrl+Left
bindkey '^[[1;3C' forward-word                    # Alt+Right
bindkey '^[[1;3D' backward-word                   # Alt+Left
bindkey '^H' backward-kill-word                   # Ctrl+Backspace
bindkey '^[[3;5~' kill-word                       # Ctrl+Delete
bindkey '^[[3~' delete-char                       # Delete key
bindkey ' ' magic-space                           # Space
bindkey "^[^?" backward-kill-slash-separated                 # Alt+Backspace

# History
HISTSIZE=5000
HISTFILE=~/.zsh_history
SAVEHIST=$HISTSIZE
HISTDUP=erase
setopt appendhistory
setopt sharehistory
setopt hist_ignore_space
setopt hist_ignore_all_dups
setopt hist_save_no_dups
setopt hist_ignore_dups
setopt hist_find_no_dups

# Aliases
alias l='eza -la --group-directories-first --icons=auto'
alias lg='lazygit'
alias v='nvim'
alias vf='nvim $(fzf)'
alias zf='__zoxide_zi'

# Suffix Aliases
alias -s json=jless
alias -s md=bat
alias -s txt=bat

# opts
setopt auto_cd

# Integrations
# FZF
export FZF_ALT_C_COMMAND="fd --type directory --hidden"
export FZF_ALT_C_OPTS="--preview 'eza -a --tree -I.git --git-ignore --icons --colour=always {} | head -n 200'"
export FZF_CTRL_T_COMMAND="fd --type file --hidden"
export FZF_CTRL_T_OPTS="--preview 'bat --color=always --style=full --line-range=:500 {}'"
export FZF_DEFAULT_COMMAND="fd --type file --hidden"
eval "$(fzf --zsh)"

# Starship prompt
eval "$(starship init zsh)"

# Zoxide (smarter cd)
eval "$(zoxide init zsh)"

# Mise (runtime version manager)
eval "$(mise activate zsh)"
