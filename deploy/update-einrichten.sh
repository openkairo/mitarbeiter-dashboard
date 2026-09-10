#!/usr/bin/env bash
# Einmalig: richtet die Update-Funktion auf dem Server ein.
#
#   ./deploy/update-einrichten.sh
#
# Legt an:
#   * einen Bereitstellungsschluessel bei GitHub — NUR lesend, nur fuer dieses
#     Repo, jederzeit widerrufbar. Kein Konto-Token auf dem Server.
#   * /opt/smg-update/repo — eine Arbeitskopie des Repos
#   * einen Cron-Eintrag, der jede Minute nach Anforderungen sieht
#
# Faesst keine bestehende Instanz an.

set -euo pipefail
ZIEL_ENV="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ziel.env"
# shellcheck disable=SC1090
[[ -f "$ZIEL_ENV" ]] && source "$ZIEL_ENV"
SERVER="${DEPLOY_SERVER:-}"
SSH_KEY="${DEPLOY_SSH_KEY:-$HOME/.ssh/id_ed25519}"
REPO_NAME="${UPDATE_REPO:-openkairo/mitarbeiter-dashboard}"
[[ -n "$SERVER" ]] || { echo "✗ DEPLOY_SERVER fehlt (deploy/ziel.env)." >&2; exit 1; }

fern() { ssh -i "$SSH_KEY" -o ConnectTimeout=15 "$SERVER" "$@"; }

echo "▸ 1/4  Schlüssel auf dem Server anlegen"
fern "mkdir -p /opt/smg-update && test -f /root/.ssh/id_smg_repo || \
      ssh-keygen -t ed25519 -N '' -C 'smg-update (nur lesend)' -f /root/.ssh/id_smg_repo -q"
OEFFENTLICH="$(fern 'cat /root/.ssh/id_smg_repo.pub')"
echo "  ✓ $(echo "$OEFFENTLICH" | cut -c1-40)…"

echo "▸ 2/4  Schlüssel bei GitHub eintragen (nur lesend)"
# Der Titel taugt nicht als Merkmal — GitHub lehnt einen bereits
# eingetragenen Schluessel unabhaengig davon ab. Verglichen wird der
# Schluessel selbst.
if gh repo deploy-key list --repo "$REPO_NAME" 2>/dev/null | grep -qF "$(echo "$OEFFENTLICH" | awk '{print $2}')"; then
    echo "  ✓ war schon da"
else
    echo "$OEFFENTLICH" > /tmp/smg-update.pub
    gh repo deploy-key add /tmp/smg-update.pub --repo "$REPO_NAME" --title "smg-update (nur lesend)"
    rm -f /tmp/smg-update.pub
    echo "  ✓ eingetragen"
fi

echo "▸ 3/4  Arbeitskopie holen"
# Der Host-Eintrag steht in einer eigenen Datei und wird eingebunden — eine
# bestehende ~/.ssh/config bleibt dabei unangetastet. Fehlt sie, wird sie
# angelegt; `Include` muss dabei ganz oben stehen.
fern "mkdir -p /root/.ssh && chmod 700 /root/.ssh
cat > /root/.ssh/config.d_smg <<'EOF'
Host github-smg
  HostName github.com
  User git
  IdentityFile /root/.ssh/id_smg_repo
  IdentitiesOnly yes
  StrictHostKeyChecking accept-new
EOF
chmod 600 /root/.ssh/config.d_smg
touch /root/.ssh/config
if ! grep -q 'config.d_smg' /root/.ssh/config; then
  printf 'Include /root/.ssh/config.d_smg\n\n' > /tmp/sshcfg
  cat /root/.ssh/config >> /tmp/sshcfg
  mv /tmp/sshcfg /root/.ssh/config
fi
chmod 600 /root/.ssh/config
if [ -d /opt/smg-update/repo/.git ]; then
  git -C /opt/smg-update/repo remote set-url origin git@github-smg:$REPO_NAME.git
  git -C /opt/smg-update/repo fetch --quiet origin main
else
  git clone --quiet git@github-smg:$REPO_NAME.git /opt/smg-update/repo
fi
git -C /opt/smg-update/repo rev-parse --short=8 origin/main"
echo "  ✓ Arbeitskopie steht"

echo "▸ 4/4  Wache einrichten"
scp -q -i "$SSH_KEY" "$(dirname "${BASH_SOURCE[0]}")/update.sh" \
                     "$(dirname "${BASH_SOURCE[0]}")/update-wache.sh" "$SERVER:/opt/smg-update/"
fern "chmod +x /opt/smg-update/*.sh
touch /var/log/smg-update.log
( crontab -l 2>/dev/null | grep -v 'smg-update/update-wache.sh' ; \
  echo '* * * * * /opt/smg-update/update-wache.sh >/dev/null 2>&1' ) | crontab -
crontab -l | grep smg-update"
echo
echo "Fertig. In den Settings steht jetzt unter „Update“ ein Knopf."
