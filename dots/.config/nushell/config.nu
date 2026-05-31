$env.EDITOR = "nvim"
$env.VISUAL = "nvim"
$env.UV_TOOL_BIN_DIR = ($env.HOME | path join ".local/share/uv/bin")

$env.config.buffer_editor = "nvim"
$env.config.show_banner = false

$env.path ++= ["~/.local/bin"]
$env.path ++= ["~/.local/armgcc/bin"]
$env.path ++= ["~/.config/composer/vendor/bin"]
$env.path ++= ["~/.local/share/uv/bin"]

source fzf.nu
source nu_scripts/themes/nu-themes/tokyo-night.nu

mkdir ($nu.data-dir | path join "vendor/autoload")
starship init nu | save -f ($nu.data-dir | path join "vendor/autoload/starship.nu")
zoxide init nushell | save -f ($nu.data-dir | path join "vendor/autoload/zoxide.nu")
mise activate nu | save -f ($nu.data-dir | path join "vendor/autoload/mise.nu")

alias l = eza -la --group-directories-first --icons=auto
alias lg = lazygit
alias v = nvim
alias vf = nvim (fzf)
alias lv = NVIM_APPNAME=lazyvim nvim
