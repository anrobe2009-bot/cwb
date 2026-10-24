# Bruecke umschalten: maxfriends -> CWB

Stand heute: vorbereitet, nichts umgeschaltet.

## Ist-Zustand (belegt)
- Dienst `bruecke`, Container `cwb_bruecke`: /home/robert/maxfriends/docker-compose.yml Zeilen 252-265
  (Build-Kontext ./bruecke, restart unless-stopped, expose 9000, kein Host-Port).
- Umgebungsvariablen (nur Namen, aus bruecke/geheimnisse.conf per env_file): BRUECKE_SECRET_PATH,
  BRUECKE_PC_TOKEN; optional BRUECKE_DB_PFAD (Standard /data/bruecke.db), server.py:22-25.
- Daten: benanntes Volume `bruecke_data` (compose Zeile 308), real `maxfriends_bruecke_data`, gemountet auf /data
  (SQLite-Datei bruecke.db: Ablagefach und Auftraege).
- Netz: `internal` (Zeilen 290-292), real `maxfriends_internal`, Subnetz 172.19.0.0/16, von maxfriends verwaltet.
- nginx findet die Bruecke ueber den DNS-Namen `bruecke:9000` (nginx/nginx.conf:28-30), geheimer Pfad per
  include nginx/geheim/bruecke.conf (nginx.conf:219). Die IP 172.19.0.10 ist NICHT fest eingetragen,
  sie wird dynamisch vergeben und darf sich aendern. Wichtig ist nur der Alias `bruecke`.

## Vorbereitet in /home/robert/CWB/bruecke
server.py, ablage.py, test_ablage.py, Dockerfile, requirements.txt, geheimnisse.conf (Kopie, Rechte 600,
in .gitignore), docker-compose.yml (Netz extern `maxfriends_internal` mit Alias `bruecke`, Volume extern
`maxfriends_bruecke_data`, Containername cwb_bruecke). Image `cwb-bruecke:latest` ist gebaut, nicht gestartet.

## Umschalten (erwartete Pause: etwa 10 bis 30 Sekunden)
1. Sicherung der Daten (Bruecke laeuft weiter):
   `docker run --rm -v maxfriends_bruecke_data:/data -v /home/robert/CWB/bruecke:/sicherung alpine tar czf /sicherung/daten_vor_umzug.tgz -C /data .`
   (Archiv nicht committen.)
2. Dienst `bruecke` in /home/robert/maxfriends/docker-compose.yml sichern (Kopie) und Zeilen 252-265 entfernen.
   Das Volume `bruecke_data` und das Netz dort NICHT entfernen.
3. Alte Bruecke weg, neue hoch (direkt hintereinander):
   `docker stop cwb_bruecke && docker rm cwb_bruecke && cd /home/robert/CWB/bruecke && docker compose up -d`
4. Pruefen: `docker ps | grep cwb_bruecke`, `docker logs cwb_bruecke --tail 20`,
   `docker network inspect maxfriends_internal | grep -A3 cwb_bruecke` (Alias `bruecke` vorhanden),
   dann Status-Werkzeug der Bruecke aus dem Chat aufrufen. nginx braucht keinen Neustart, loest aber den Namen
   beim Start auf: falls 502, `docker exec <nginx> nginx -s reload`.
5. Kuenftig in maxfriends nie `docker compose down -v` ausfuehren (loescht das Volume).

## Zurueck, falls etwas schiefgeht (etwa 30 Sekunden)
1. `cd /home/robert/CWB/bruecke && docker compose down` (ohne -v!)
2. Gesicherte maxfriends-docker-compose.yml zurueckkopieren, dann
   `cd /home/robert/maxfriends && docker compose up -d bruecke`
3. Daten liegen unveraendert im selben Volume; bei Beschaedigung Archiv aus Schritt 1 zurueckspielen.

## Hinweise
- Compose-Projektname der neuen Datei ist `cwb_bruecke`; maxfriends meldet danach ggf. keine Waisen mehr.
- Das Volume gehoert technisch weiter zum Projekt maxfriends (Label); `external: true` verhindert, dass CWB es anlegt oder loescht.
