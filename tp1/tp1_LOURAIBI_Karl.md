https://app.notion.com/p/sysentive/TP1-piloter-Docker-par-son-API-en-Bash-et-jq-405a84550c7680c383fbfe9b10eeeb9e


1.1 : dapi GET /version | jq la version est : 29.9.2 

user@Anas:~/tp-docker$ dapi GET /version | jq
→ HTTP 200
{
  "Platform": {
    "Name": "Docker Desktop 4.96.3 (244472)"
  },
  "Version": "29.9.2",
  "ApiVersion": "1.56",
  "MinAPIVersion": "1.40",
  "Os": "linux",
  "Arch": "amd64",
  "Components": [
    {
      "Name": "Engine",
      "Version": "29.9.2",
      "Details": {
        "ApiVersion": "1.56",
        "Arch": "amd64",
        "BuildTime": "2026-10-20T18:45:02.000000000+00:00",
        "Experimental": "false",
        "GitCommit": "0367cbe",
        "GoVersion": "go1.26.10",
        "KernelVersion": "6.18.54.1-microsoft-standard-WSL2",
        "MinAPIVersion": "1.40",
        "Module": "github.com/moby/moby/v2",
        "ModuleVersion": "v2.0.0+unknown",
        "Os": "linux"
      }
    },
    {
      "Name": "containerd",
      "Version": "v2.4.2",
      "Details": {
        "GitCommit": "b7a25261e029d68978bbf290df0a62fc819b3c51"
      }
    },
    {
      "Name": "runc",
      "Version": "1.5.2",
      "Details": {
        "GitCommit": "v1.5.2-0-g29dd3dc2"
      }
    },
    {
      "Name": "docker-init",
      "Version": "0.19.0",
      "Details": {
        "GitCommit": "de40ad0"
      }
    }
  ],
  "GitCommit": "0367cbe",
  "GoVersion": "go1.26.10",
  "KernelVersion": "6.18.54.1-microsoft-standard-WSL2",
  "BuildTime": "2026-10-20T18:45:02.000000000+00:00"
}





1.2 user@Anas:~/tp-docker$ dapi GET /info | jq '{Containers, ContainersRunning, Images, OperatingSystem, NCPU}'

user@Anas:~/tp-docker$ dapi GET /info | jq '{Containers, ContainersRunning, Images, OperatingSystem, NCPU}'
→ HTTP 200
{
  "Containers": 2,
  "ContainersRunning": 0,
  "Images": 2,
  "OperatingSystem": "Docker Desktop",
  "NCPU": 8
}

1.3 user@Anas:~/tp-docker$ dapi GET /info | jq '.MemTotal / 1024 / 1024 / 1024 | round'

/ 1024 / 1024 / 1024 -> Sert a convertir en Gi car .MemTotal est en octet 

user@Anas:~/tp-docker$ dapi GET /info | jq '.MemTotal / 1024 / 1024 / 1024 | round'
→ HTTP 200
8


1.4 dapi GET '/containers/json?all=true' | jq '.[] | "\(.Names[0][1:]) \(.State) \(.Image)"'

La commande /containers/json permet de récupérer la liste des conteneurs Docker. On ajoute ?all=true pour afficher tous les conteneurs, même ceux qui sont arrêtés. Le ? sert à ajouter un paramètre à l'URL et all=true indique qu'on souhaite tous les afficher.

comme dit dans le tp: .Names : est Names est un tableau dont les noms commencent par / ; @tsv ou une interpolation "\(.a) \(.b)".
[0] : sélectionne le premier nom du tableau.
[1:] : supprime le premier caractère du nom, qui est / , @tsv ou une interpolation "\(.a) \(.b) 

user@Anas:~/tp-docker$ dapi GET '/containers/json?all=true' | jq '.[] | "\(.Names[0][1:]) \(.State) \(.Image)"'
→ HTTP 200
"mon-nginx exited nginx"
"exciting_chatelet exited hello-world"

1.5 Listez les images présentes (leurs tags) : 

user@Anas:~/tp-docker$ dapi GET /images/json | jq -r '.[].RepoTags[]?'
→ HTTP 200
nginx:latest
hello-world:latest

 puis affichez la taille totale de toutes les images, en Mo.
 
user@Anas:~/tp-docker$ dapi GET /images/json | jq '(map(.Size) | add) / 1000000'
→ HTTP 200
243.318267


Partie 2 : le cycle de vie d'un conteneur

user@Anas:~/tp-docker$ dapi POST '/images/create?fromImage=nginx&tag=alpine' | tail -n 3
→ HTTP 200
{"status":"Pull complete","progressDetail":{"hidecounts":true},"id":"b9b388a21ecf"}
{"status":"Digest: sha256:a3554c0d0b48177b1413c26e01f695334428020d9df01243fbae3e11cfd17417"}
{"status":"Status: Downloaded newer image for nginx:alpine"}


2.2 : user@Anas:~/tp-docker$ BODY=$(jq -n '{
  Image: "nginx:alpine",
  Labels: {tp: "api-rest"},
  ExposedPorts: {"80/tcp": {}},
  HostConfig: {PortBindings: {"80/tcp": [{HostPort: "8088"}]}}
}')
user@Anas:~/tp-docker$ dapi POST '/containers/create?name=web-tp1' "$BODY" | jq
→ HTTP 20{
1
  "Id": "c07f4e8bec1382d850461b063fd40e41dc5409545d0ff6e761ed0b77e3cb958a",
  "Warnings": []
}

Notez l'identifiant renvoyé: 201

user@Anas:~/tp-docker$ dapi POST '/containers/create?name=web-tp1' "$BODY" | jq
→ HTTP 4{
09
  "message": "Conflict. The container name \"/web-tp1\" is already in use by container \"c07f4e8bec1382d850461b063fd40e41dc5409545d0ff6e761ed0b77e3cb958a\". You have to remove (or rename) that container to be able to reuse that name."
}

 Relancez exactement la même commande : quel code obtenez-vous, et que dit le message ? 209, le message dot que le coteneur web-tp1 existe deja et qu'on doit soit le supprimer ou soit le renomer pour que le nouveau conteneur soit utilisable avec ce nom 

 user@Anas:~/tp-docker$ dapi POST /containers/web-tp1/start
→ HTTP 204 = Demarrage reussi mais la requete n'a pas de corps ( le docker il peux pas envoyer une info supplementaire qu'il a pas )


user@Anas:~/tp-docker$ dapi POST /containers/web-tp1/start
→ HTTP 304 = pas de modification, le conteneur est deja demarrer et y'a pas eu de modification depuis la derniere requete


2.4
user@Anas:~/tp-docker$ dapi GET /containers/web-tp1/json | jq '{
  Etat: .State.Status,
  Demarrage: .State.StartedAt,
  Port: .NetworkSettings.Ports["80/tcp"][0].HostPort,
  Labels: .Config.Labels
}'
→ HTTP 200
{
  "Etat": "running",
  "Demarrage": "2026-10-26T11:34:11.970072937Z",
  "Port": "8088",
  "Labels": {
    "desktop.docker.io/wsl-distro": "Ubuntu",
    "maintainer": "NGINX Docker Maintainers <docker-maint@nginx.com>",
    "tp": "api-rest"
  }
}

2.5 
dapi DELETE /containers/web-tp1

user@Anas:~/tp-docker$ dapi DELETE /containers/web-tp1
{"message":"cannot remove container \"web-tp1\": container is running: stop the container before removing or force remove"}
→ HTTP 409

On peux pas suppriper le conteneur tant que ce dernier est en start. Ce n'est pas une erreur 400, car la requête est valide, ni une erreur 403, car ce n'est pas un problème d'autorisation.

2.6 
user@Anas:~/tp-docker$ dapi POST '/containers/web-tp1/stop?t=5'
→ HTTP 204 -> conteneur arreter 
user@Anas:~/tp-docker$ dapi POST '/containers/web-tp1/stop?t=5'
→ HTTP 304  -> conteneur deja arreter y'a aucune autre executiona faire coté docker 

Le paramètre t=5 = Docker laisse 5 secondes maximum au conteneur pour s'arrêter

2.7 
user@Anas:~/tp-docker$ dapi DELETE /containers/web-tp1
→ HTTP 204 -> conteneur supprimer 
user@Anas:~/tp-docker$ dapi DELETE /containers/web-tp1/json
{"message":"No such container: web-tp1"}
→ HTTP 404 = ne trouve pas le conteneur ça a bien ete supp ( introuvable ) 



Partie 3 : exécuter une commande, lire les logs

user@Anas:~/tp-docker$ EXEC_ID=$(dapi POST /containers/web-tp1/exec "$(jq -n '{
  Cmd: ["sh", "-c", "nginx -v; head -n 2 /etc/os-release"],
  AttachStdout: true, AttachStderr: true, Tty: true
}')" | jq -r .Id)
→ HTTP 201

user@Anas:~/tp-docker$ dapi POST "/exec/$EXEC_ID/start" '{"Detach": false, "Tty": true}'
nginx version: nginx/1.31.8
NAME="Alpine Linux"
ID=alpine
→ HTTP 200
user@Anas:~/tp-docker$ dapi GET "/exec/$EXEC_ID/json" | jq '{ExitCode, Running}'
→ HTTP 20{
0
  "ExitCode": 0,
  "Running": false
}






