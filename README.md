# Odio Audio - Home Assistant Integration

Intégration HACS pour contrôler votre système audio PulseAudio via l'API go-odio-api.

## Fonctionnalités

- **Media Player Receiver principal** : Contrôle global de votre système audio
- **Media Players par service** : Chaque service audio (MPD, Snapcast, Shairport-Sync, etc.) devient une entité contrôlable
- **Media Players clients distants** : Détection automatique des clients réseau (tunnels PipeWire, Kodi, etc.)
- **Mise à jour optimisée** : Polling rapide pour les clients audio (5s par défaut), lent pour les services (60s par défaut)
- **Association d'entités** : Possibilité de lier les services et clients à des entités media_player existantes
- **Contrôle complet** :
  - Activation/désactivation des services
  - Contrôle du volume (global et par client)
  - Contrôle du mute (global et par client)
  - Lecture de l'état (playing/idle/off)
  - Informations détaillées sur les clients actifs

## Installation

### Via HACS (recommandé)

1. Assurez-vous que [HACS](https://hacs.xyz/) est installé
2. Ajoutez ce dépôt comme dépôt personnalisé dans HACS
3. Recherchez "Odio Audio" dans HACS
4. Cliquez sur "Télécharger"
5. Redémarrez Home Assistant

### Installation manuelle

1. Copiez le dossier `custom_components/odio_remote` dans votre dossier `config/custom_components/`
2. Redémarrez Home Assistant

## Configuration

1. Allez dans **Paramètres** → **Appareils et services**
2. Cliquez sur **Ajouter une intégration**
3. Recherchez "Odio Audio"
4. Entrez l'URL de votre API go-odio-api (ex: `http://192.168.1.100:8018`)
5. Configurez les intervalles de scan :
   - **Audio scan interval** : 5 secondes (recommandé) - fréquence de mise à jour des clients audio
   - **Service scan interval** : 60 secondes (recommandé) - fréquence de mise à jour des services
6. **Association des services (optionnel mais recommandé)** :
   - Pour chaque service, vous pouvez l'associer à une entité `media_player` existante
   - Par exemple : associer `user/mpd.service` à `media_player.music_player_daemon`
   - **Avantages** : L'entité Odio hérite de toutes les capacités de l'entité associée (play/pause, next, album art, etc.)

### Reconfiguration (associations après coup)

Vous pouvez modifier les associations à tout moment :

1. Allez dans **Paramètres** → **Appareils et services** → **Odio Audio**
2. Cliquez sur **Configurer** (icône d'engrenage)
3. Choisissez **"Gérer les associations d'entités"**
4. Associez ou dissociez vos services et **clients distants** (nouveauté !)
5. Les changements sont appliqués immédiatement

Vous pouvez maintenant également associer les **clients distants** (tunnels PipeWire, Kodi, etc.) à des entités existantes ! Par exemple, associer votre `Tunnel for kodi` à `media_player.kodi_htpc` pour bénéficier de toutes les fonctionnalités Kodi tout en contrôlant le service audio.

### Pourquoi associer les services et clients ?

Lorsqu'un service ou client distant est associé à une entité existante, l'entité Odio devient un **proxy enrichi** qui combine :
- **Contrôle du service** (on/off via systemd - services uniquement)
- **Contrôle audio PulseAudio** (mute et volume indépendants)
- **Toutes les fonctionnalités de l'entité associée** : play, pause, next, previous, seek, shuffle, repeat, source selection, album art, progression, etc.

**Exemple service :** Si vous associez `user/mpd.service` à `media_player.music_player_daemon` :
- ✅ **Turn On/Off** : Active/désactive le service MPD via systemd
- ✅ **Play/Pause/Next/Previous** : Délégués à l'entité MPD
- ✅ **Album art, titre, artiste** : Récupérés depuis l'entité MPD
- ✅ **Mute** : Contrôlé via PulseAudio (indépendant du mute MPD)
- ✅ **Volume** : Priorité à l'entité MPD, fallback sur PulseAudio

**Exemple client distant :** Si vous associez `Tunnel for xbmc@htpc` à `media_player.kodi_htpc` :
- ✅ **Play/Pause/Next/Previous** : Délégués à l'entité Kodi
- ✅ **Album art, titre, artiste, progression** : Récupérés depuis l'entité Kodi
- ✅ **Mute** : Contrôlé via PulseAudio (coupe le son du tunnel sans toucher à Kodi)
- ✅ **Volume** : Priorité à l'entité Kodi, fallback sur PulseAudio
- ℹ️ **Pas de Turn On/Off** : Les clients distants n'ont pas de service systemd local

## Structure des entités

### Receiver Principal
Représente le **serveur audio PulseAudio/PipeWire** et agrège tous les clients audio actifs.

- **État** :
  - `playing` : Au moins un client est en lecture
  - `idle` : Des clients sont connectés mais aucun ne joue
  - `off` : Aucun client connecté
- **Actions** :
  - `volume_set` : Contrôle le volume global du serveur (via `/audio/server/volume`)
  - `volume_mute` : Mute global du serveur (via `/audio/server/mute`)
- **Attributs** :
  - `active_clients` : Nombre de clients actifs
  - `playing_clients` : Nombre de clients en lecture
  - `server_name` : Nom du serveur PulseAudio
  - `server_hostname` : Hostname du serveur
  - `default_sink` : Sink par défaut

**Note :** Le receiver principal représente déjà le serveur audio (PulseAudio/PipeWire). Les services `pulseaudio.service` et `pipewire-pulse.service` ne génèrent donc PAS d'entités séparées car ils ne sont pas des lecteurs mais le serveur lui-même.

### Services Audio (Children)
Chaque service audio client activé (MPD, Snapcast, Spotifyd, Shairport-Sync, upmpdcli) devient une entité avec :

- **État** :
  - `off` : Service arrêté
  - `idle` : Service démarré mais pas de lecture
  - `playing` : Service en lecture
  - `paused` : Service en pause (si associé à une entité qui supporte pause)
- **Actions natives** :
  - `turn_on` : Active et redémarre le service
  - `turn_off` : Désactive le service
  - `volume_mute` : Contrôle du mute PulseAudio du client
  - `volume_set` : Contrôle du volume PulseAudio du client (via `/audio/clients/{name}/volume`)
- **Actions héritées** (si service associé à une entité) :
  - `play`, `pause`, `stop` : Contrôle de lecture
  - `next_track`, `previous_track` : Navigation
  - `seek` : Recherche dans le média
  - `shuffle_set`, `repeat_set` : Modes de lecture
  - `select_source` : Sélection de source
  - `volume_set` : Contrôle du volume
- **Attributs natifs** :
  - `scope` : system ou user
  - `enabled` : Service activé au démarrage
  - `active_state` : État systemd
  - `client_id` : ID du client audio associé
  - `app`, `backend`, `user`, `host` : Informations du client
  - `mapped_entity` : Entité associée (si configuré)
- **Attributs hérités** (si service associé) :
  - `media_title`, `media_artist`, `media_album_name` : Métadonnées
  - `media_duration`, `media_position` : Progression
  - `entity_picture` : Album art
  - `shuffle`, `repeat` : Modes de lecture
  - `source`, `source_list` : Sources disponibles

### Clients Standalone (Children automatiques)
Les clients **distants** (host différent du serveur) qui se connectent directement au serveur PulseAudio/PipeWire sans service systemd local génèrent automatiquement des entités lors de leur première connexion :

**Critères de détection :**
- Le `host` du client est différent du `hostname` du serveur
- Aucun service systemd local ne correspond à ce client
- Exemples : tunnels PipeWire TCP, connexions réseau DLNA/UPnP

**Identification stable :**
- Les entités sont identifiées par le **nom** du client (pas l'ID qui change à chaque reconnexion)
- Exemple : `Tunnel for bobby@bobby-desktop` génère `media_player.tunnel_for_bobby_bobby_desktop`
- À la reconnexion, l'entité existante est réutilisée (même si l'ID PulseAudio a changé)

**État et actions :**
- **État** :
  - `off` : Client déconnecté (l'entité reste visible)
  - `idle` : Client connecté mais pas de lecture
  - `playing` : Client en lecture
  - `paused` : Client en pause (si associé à une entité qui supporte pause)
- **Actions natives** :
  - `volume_mute` : Contrôle du mute PulseAudio du client
  - `volume_set` : Contrôle du volume PulseAudio du client (via `/audio/clients/{name}/volume`)
- **Actions héritées** (si client associé à une entité) :
  - `play`, `pause`, `stop` : Contrôle de lecture
  - `next_track`, `previous_track` : Navigation
  - `seek` : Recherche dans le média
  - `shuffle_set`, `repeat_set` : Modes de lecture
  - `select_source` : Sélection de source

**Attributs :**
- `client_name` : Nom stable du client
- `remote_host` : Hostname du client distant
- `server_hostname` : Hostname du serveur audio
- `status` : `connected` ou `disconnected`
- `mapped_entity` : Entité associée (si configuré)
- `client_id` : ID PulseAudio actuel (change à chaque reconnexion)
- `app`, `backend`, `user` : Informations du client
- `connection` : Détails de connexion (ex: "TCP/IP client from 192.168.1.24:50324")
- `app_version` : Version de l'application cliente
- **Attributs hérités** (si client associé) :
  - `media_title`, `media_artist`, `media_album_name` : Métadonnées
  - `media_duration`, `media_position` : Progression
  - `entity_picture` : Album art
  - `shuffle`, `repeat` : Modes de lecture
  - `source`, `source_list` : Sources disponibles

**Exemples :**
```yaml
# Client: {"name": "Tunnel for bobby@bobby-desktop", "host": "bobby-desktop"}
# Serveur: {"hostname": "rasponkyo"}
# → Entité créée car bobby-desktop ≠ rasponkyo

# Client: {"name": "Playback", "app": "Snapcast", "host": "rasponkyo"}
# Serveur: {"hostname": "rasponkyo"}
# → PAS d'entité standalone car même host + déjà géré par snapclient.service
```

## Services supportés

### Lecteurs audio (génèrent des entités children) :
- **MPD** (Music Player Daemon)
- **Shairport-Sync** (AirPlay)
- **Snapcast** (Client audio multi-room)
- **Spotifyd** (Client Spotify)
- **upmpdcli** (UPnP Renderer)

### Exclus (ne génèrent PAS d'entités) :
- **MPD Disc Player** : Relaye simplement vers MPD pour les disques/USB
- **PulseAudio / PipeWire-Pulse** : Ce sont les serveurs audio eux-mêmes, déjà représentés par le receiver principal

## Exemple d'automatisation

```yaml
# Contrôle du volume global
automation:
  - alias: "Volume global à 50% la nuit"
    trigger:
      - platform: time
        at: "22:00:00"
    action:
      - service: media_player.volume_set
        target:
          entity_id: media_player.odio_remote_receiver
        data:
          volume_level: 0.5

# Mute global en mode silence
automation:
  - alias: "Mute global en mode silence"
    trigger:
      - platform: state
        entity_id: input_boolean.silence_mode
        to: 'on'
    action:
      - service: media_player.volume_mute
        target:
          entity_id: media_player.odio_remote_receiver
        data:
          is_volume_muted: true

# Activer Snapcast quand on lance une lecture
automation:
  - alias: "Démarrer Snapcast sur lecture"
    trigger:
      - platform: state
        entity_id: media_player.salon_chromecast
        to: 'playing'
    action:
      - service: media_player.turn_on
        target:
          entity_id: media_player.snapclient_service_user

# Utiliser l'entité Odio enrichie pour contrôler MPD
automation:
  - alias: "Pause MPD quand téléphone sonne"
    trigger:
      - platform: state
        entity_id: sensor.phone_state
        to: 'ringing'
    action:
      # L'entité Odio délègue la pause à l'entité MPD associée
      - service: media_player.media_pause
        target:
          entity_id: media_player.mpd_service_user

# Contrôler le volume d'un client spécifique
automation:
  - alias: "Baisser le volume du tunnel bobby le soir"
    trigger:
      - platform: time
        at: "22:00:00"
    condition:
      - condition: state
        entity_id: media_player.tunnel_for_bobby_bobby_desktop
        state: 'playing'
    action:
      - service: media_player.volume_set
        target:
          entity_id: media_player.tunnel_for_bobby_bobby_desktop
        data:
          volume_level: 0.3

# Afficher l'album art dans une carte
type: media-control
entity: media_player.mpd_service_user
# L'album art vient de l'entité MPD associée

# Créer un script pour éteindre tout l'audio
script:
  audio_off:
    sequence:
      # Éteindre tous les services audio
      - service: media_player.turn_off
        target:
          entity_id:
            - media_player.mpd_service_user
            - media_player.snapclient_service_user
            - media_player.spotifyd_service_user

# Automatisation avancée avec navigation
automation:
  - alias: "Skip chanson sur double-clic bouton"
    trigger:
      - platform: state
        entity_id: binary_sensor.button
        to: 'on'
        for: "00:00:00.5"
    action:
      # Next track délégué à l'entité associée
      - service: media_player.media_next_track
        target:
          entity_id: media_player.mpd_service_user
```

## API requise

Cette intégration nécessite que votre API go-odio-api expose les endpoints suivants :

**Endpoints de lecture :**
- `GET /audio/server` : Informations serveur
- `GET /audio/clients` : Liste des clients audio
- `GET /services` : Liste des services

**Endpoints de contrôle audio :**
- `POST /audio/server/mute` : Mute global du serveur (payload: `{"muted": true}`)
- `POST /audio/server/volume` : Volume global du serveur (payload: `{"volume": 0.5}`)
- `POST /audio/clients/{name}/mute` : Mute d'un client spécifique (payload: `{"muted": true}`)
- `POST /audio/clients/{name}/volume` : Volume d'un client spécifique (payload: `{"volume": 0.5}`)

**Endpoints de contrôle services :**
- `POST /services/{scope}/{unit}/enable` : Activer un service
- `POST /services/{scope}/{unit}/disable` : Désactiver un service
- `POST /services/{scope}/{unit}/restart` : Redémarrer un service

**Notes importantes :**
- Les endpoints `{name}` utilisent le **nom** du client PulseAudio, pas l'ID
- Le volume est une valeur float entre 0.0 (muet) et 1.0 (100%)
- Les endpoints `/audio/server/*` contrôlent tous les clients en une seule opération

### ⚠️ Important : Endpoint de mute

PulseAudio identifie les sinks par leur **nom** (pas leur ID numérique). L'endpoint de mute doit donc utiliser le champ `name` du client :

```
POST /audio/clients/Music Player Daemon/mute
POST /audio/clients/Tunnel for bobby@bobby-desktop/mute
```

**Attention :** Les noms peuvent contenir des espaces et caractères spéciaux. Assurez-vous que votre API Go gère correctement l'URL encoding :

```go
// Dans votre router Go
router.HandleFunc("/audio/clients/{name}/mute", handleMute)

// Dans le handler
vars := mux.Vars(r)
clientName := vars["name"]  // Gorilla Mux décode automatiquement l'URL
```

### ⚠️ Important : Content-Type

**L'intégration gère automatiquement les réponses en `text/plain` et `application/json`**, mais il est fortement recommandé de configurer votre API Go pour retourner le Content-Type correct :

```go
// Dans votre API Go, ajoutez ce header :
w.Header().Set("Content-Type", "application/json")
w.Write(jsonData)
```

Si vous voyez une erreur comme `Attempt to decode JSON with unexpected mimetype: text/plain`, c'est que votre API Go retourne le mauvais Content-Type. L'intégration fonctionnera quand même, mais il vaut mieux corriger l'API.

## Dépannage

### Étape 1 : Tester la connexion API manuellement

Avant de configurer dans Home Assistant, testez votre API avec le script fourni :

```bash
cd /config/custom_components/odio_remote
python test_api_connection.py http://VOTRE_IP:8018
```

**Ce que vous devriez voir :**
```
Testing connection to: http://192.168.1.6:8018
------------------------------------------------------------

1. Testing /audio/server endpoint...
   URL: http://192.168.1.6:8018/audio/server
   Status: 200
   Content-Type: text/plain; charset=utf-8  # ⚠️ Devrait être application/json
   Raw response: {"kind":"pulseaudio","name":"pulseaudio",...
   ✓ Success! Server: {'kind': 'pulseaudio', ...}

2. Testing /audio/clients endpoint...
   ✓ Success! Found 2 clients

3. Testing /services endpoint...
   ✓ Success! Found 16 services
   Enabled services: 5

✓ All tests passed!
```

Si vous voyez `Content-Type: text/plain` au lieu de `application/json`, l'intégration fonctionnera quand même car elle parse manuellement le JSON, mais il est recommandé de corriger votre API Go.

### Étape 2 : Activer les logs détaillés

Ajoutez ceci dans votre `configuration.yaml` et redémarrez HA :

```yaml
logger:
  default: warning
  logs:
    custom_components.odio_remote: debug
    custom_components.odio_remote.config_flow: debug
    custom_components.odio_remote.media_player: debug
```

### Problème : "Cannot connect to API" lors du setup

**Causes possibles :**

1. **URL incorrecte** : Vérifiez que l'URL est complète
   - ✓ Correct : `http://192.168.1.100:8018`
   - ✗ Incorrect : `192.168.1.100:8018` (manque http://)
   - ✗ Incorrect : `http://192.168.1.100:8018/` (slash final)

2. **API non accessible depuis Home Assistant** :
   ```bash
   # Depuis le serveur Home Assistant, testez :
   curl http://VOTRE_IP:8018/audio/server
   curl http://VOTRE_IP:8018/services
   ```

3. **Firewall** : Assurez-vous que le port est ouvert

4. **CORS** : Si l'API est derrière un proxy, vérifiez les headers CORS

### Les services n'apparaissent pas
- Vérifiez que les services sont activés (`enabled: true`)
- Vérifiez que les services existent (`exists: true`)
- Consultez les logs pour voir quels services sont détectés :
  ```
  grep "Found.*enabled services" home-assistant.log
  ```

### Les états ne se mettent pas à jour
- Vérifiez la connectivité à l'API : `curl http://IP:8018/audio/clients`
- Réduisez les intervalles de scan dans les options de l'intégration
- Vérifiez les logs :
  ```
  grep "odio_remote" home-assistant.log | tail -50
  ```

### Erreur "Timeout communicating with API"
- Augmentez les timeouts dans le code (actuellement 10s pour audio, 15s pour services)
- Vérifiez que votre serveur répond rapidement : `time curl http://IP:8018/services`

### Debug avancé

Pour voir TOUTES les requêtes HTTP :

```yaml
logger:
  default: warning
  logs:
    custom_components.odio_remote: debug
    homeassistant.helpers.aiohttp_client: debug
```

## Licence

MIT

## Contribution

Les contributions sont les bienvenues ! N'hésitez pas à ouvrir une issue ou une pull request.
