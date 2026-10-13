"""KChrono — cliente Firebase (reaproveitado do CTAD-Upload-Auto).

Autentica EXATAMENTE como o site (Firebase Auth via Identity Toolkit) e
escreve no Realtime Database via REST com o token do usuário, respeitando
as regras — sem chave de serviço.
"""
from __future__ import annotations

import time

import requests


class ErroAuth(Exception):
    pass


class ErroBanco(Exception):
    pass


NIVEIS_UPLOAD = ("superuser", "admin", "gestor")


class CtadClient:
    def __init__(self, cfg):
        fb = cfg.get("firebase", {})
        urls = cfg.get("auth_urls", {})
        self.apikey = fb.get("apiKey", "")
        self.db = fb.get("databaseURL", "").rstrip("/")
        self.bucket = fb.get("storageBucket", "")
        self.identity = urls.get("identity", "https://identitytoolkit.googleapis.com/v1")
        self.secure = urls.get("securetoken", "https://securetoken.googleapis.com/v1")
        self.email = cfg.get("email", "")
        self.password = cfg.get("password", "")
        self.timeout = int(cfg.get("timeout_segundos", 60))
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": "KChrono/0.2.0"})
        self.id_token = None
        self.refresh_token = None
        self.uid = None
        self.expira_em = 0
        self.nivel = None

    def login(self):
        try:
            r = self.s.post(f"{self.identity}/accounts:signInWithPassword",
                            params={"key": self.apikey},
                            json={"email": self.email, "password": self.password,
                                  "returnSecureToken": True},
                            timeout=self.timeout)
        except requests.RequestException as e:
            raise ErroAuth(f"Sem conexão com o Auth: {e}")
        if r.status_code != 200:
            detalhe = ""
            try:
                detalhe = r.json().get("error", {}).get("message", "")
            except ValueError:
                pass
            raise ErroAuth(f"Login recusado ({r.status_code} {detalhe}). "
                           "Confira e-mail/senha da conta.")
        js = r.json()
        self.id_token = js["idToken"]
        self.refresh_token = js["refreshToken"]
        self.uid = js["localId"]
        self.expira_em = time.time() + int(js.get("expiresIn", "3600"))
        self.nivel = self._verificar_acesso()
        return self.nivel

    def _verificar_acesso(self):
        nivel = self.rtdb_get(f"usuarios/{self.uid}/nivel")
        if nivel in NIVEIS_UPLOAD:
            return nivel
        legado = self.rtdb_get(f"admins/{self.uid}")
        if legado is True:
            return "admin"
        raise ErroAuth(f"Conta '{self.email}' sem nível de upload (nível={nivel}). "
                       "Peça ao superuser para aprovar/vincular a conta.")

    def _token(self):
        if not self.id_token:
            self.login()
        elif time.time() > self.expira_em - 300:
            try:
                r = self.s.post(f"{self.secure}/token",
                                params={"key": self.apikey},
                                data={"grant_type": "refresh_token",
                                      "refresh_token": self.refresh_token},
                                timeout=self.timeout)
                r.raise_for_status()
                js = r.json()
                self.id_token = js["id_token"]
                self.refresh_token = js.get("refresh_token", self.refresh_token)
                self.expira_em = time.time() + int(js.get("expires_in", "3600"))
            except requests.RequestException:
                self.login()
        return self.id_token

    def rtdb_get(self, caminho, params=None):
        q = dict(params or {})
        q["auth"] = self._token()
        try:
            r = self.s.get(f"{self.db}/{caminho}.json", params=q, timeout=self.timeout)
        except requests.RequestException as e:
            raise ErroBanco(f"Falha de conexão ao ler {caminho}: {e}")
        if r.status_code in (401, 403):
            self.login()
            q["auth"] = self.id_token
            r = self.s.get(f"{self.db}/{caminho}.json", params=q, timeout=self.timeout)
        if r.status_code != 200:
            raise ErroBanco(f"Leitura {caminho} -> HTTP {r.status_code}")
        return r.json()

    def rtdb_put(self, caminho, dados):
        try:
            r = self.s.put(f"{self.db}/{caminho}.json", params={"auth": self._token()},
                           json=dados, timeout=self.timeout)
        except requests.RequestException as e:
            raise ErroBanco(f"Falha de conexão ao gravar {caminho}: {e}")
        if r.status_code in (401, 403):
            self.login()
            r = self.s.put(f"{self.db}/{caminho}.json", params={"auth": self.id_token},
                           json=dados, timeout=self.timeout)
        if r.status_code != 200:
            raise ErroBanco(f"Gravação {caminho} -> HTTP {r.status_code}: {r.text[:200]}")
        return True

    def existe_hash(self, file_hash):
        js = self.rtdb_get("baterias", params={"orderBy": '"fileHash"',
                                               "equalTo": f'"{file_hash}"',
                                               "limitToFirst": 1})
        if js:
            chave, reg = next(iter(js.items()))
            return True, (reg.get("nomeArquivoOriginal") or reg.get("sessao") or chave)
        return False, None

    def salvar_bateria(self, bat_key, upload_data, resumo):
        self.rtdb_put(f"baterias/{bat_key}", upload_data)
        try:
            self.rtdb_put(f"publicResumo/baterias/{bat_key}", resumo)
        except ErroBanco as e:
            raise ErroBanco(f"Bateria salva, mas resumo falhou: {e}")
        self.rtdb_put(f"uploadLog/{bat_key}",
                      {"uid": self.uid, "acao": "upload", "bateriaKey": bat_key,
                       "fileHash": upload_data.get("fileHash"),
                       "timestamp": int(time.time() * 1000)})

    def testar_conexao(self):
        nivel = self.login()
        return {"nivel": nivel, "uid": self.uid}
