Storage Check - standalone R36S/PortMaster diagnostic

Install both items into your console's ports directory:
  Storage Check.sh
  storage-check/ (contains Python helpers)
Do not copy this tool into the PD2 game folder.

Run Storage Check from Ports menu as normal user.
Screen 1: mounted storage partitions, total/available space.
          HOME filesystem is highlighted in cyan/green and marked HOME.
Screen 2: PD2 components under HOME/.local/share/pd2-r36s,
          presence, role, allocated disk usage and install paths.
          Required production runtime/prefix first; extras/backups after.

Controls (corrected for R36S face labels):
  A: switch screen
  B: close
  Left/Right: switch screen
  Up/Down: scroll component list
Keyboard: Enter/Space switch, Escape close, arrows navigate.

Full text report: storage-check-report.txt beside the launcher.
Live native UI startup/error log: storage-check-ui.log beside the launcher.
SSH without display: bash 'Storage Check.sh' --report-only

Requires bash, Python 3, SDL2 and passwordless sudo for native display access.
No SDL_ttf, pygame, game files, Wine execution or PortMaster viewer required.
Disk inventory runs as normal user. Only SDL display helper uses sudo.
Run after exiting other games/tools normally. Native UI restores its SDL
resources on exit; no services, compositor or ES processes are killed.

PRESENT means path exists, not full runtime integrity/compatibility verification.
Disk usage uses du allocated blocks, without following symlinks or crossing
filesystems. Btrfs compression/reflinks/hard links can make exclusive physical
usage differ. Extras include historical experiments/backups, not requirements.
No application files are deleted, installed or changed.
Report is overwritten; private temporary UI data is removed on exit.
Review report before sharing: includes local paths and partition information.
