$env.config.buffer_editor = "nvim"
$env.config.show_banner = false

$env.path ++= ["~/.local/bin"]
$env.path ++= ["~/.local/share/nova/bin"]
$env.path ++= ["~/.local/armgcc/bin"]
$env.path ++= ["~/.local/share/JetBrains/Toolbox/scripts"]
$env.EDITOR = "nvim"

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
