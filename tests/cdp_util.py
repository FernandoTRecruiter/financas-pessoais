# -*- coding: utf-8 -*-
"""
cdp_util.py: Edge ou Chrome headless controlado por CDP (DevTools Protocol), para os testes.

Uso:
    from cdp_util import Edge
    with Edge(1440, 900) as ed:
        ed.ir("file:///...index.html")
        print(ed.js("document.title"))
        ed.foto("saida.png")
        print(ed.erros())

Cuidados: perfil próprio e curto na pasta temporária (um por rodada), porta que
ninguém usa, e no fim fecha SÓ o navegador que ele mesmo abriu.
"""
import base64, json, os, random, shutil, socket, subprocess, sys, tempfile, time, urllib.request
import websocket

def achar_navegador():
    """Edge ou Chrome, no Windows, macOS ou Linux (variável NAVEGADOR manda, se existir)."""
    if os.environ.get("NAVEGADOR"):
        return os.environ["NAVEGADOR"]
    candidatos = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]
    for c in candidatos:
        if os.path.exists(c):
            return c
    for nome in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
        achado = shutil.which(nome)
        if achado:
            return achado
    raise SystemExit("Nenhum Edge/Chrome encontrado. Defina NAVEGADOR=/caminho/do/navegador.")


EDGE = achar_navegador()


class Edge:
    def __init__(self, largura=1440, altura=900, escala=1):
        self.w, self.h, self.escala = largura, altura, escala

    def __enter__(self):
        # Porta sorteada e perfil com o número do processo: duas baterias rodando juntas não pegam
        # a mesma porta nem fecham o navegador uma da outra (aconteceu em 22-out).
        inicio = random.randint(9300, 9800)
        self.porta = next(p for p in range(inicio, inicio + 200) if socket.socket().connect_ex(("127.0.0.1", p)) != 0)
        self.marca = f"{os.getpid()}_{self.porta}"
        self.perfil = os.path.join(tempfile.gettempdir(), f"edgepaoli{self.marca}")
        subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={self.porta}", f"--user-data-dir={self.perfil}",
                          "--no-first-run", "--no-default-browser-check", "--disable-sync", "--hide-scrollbars",
                          "--allow-file-access-from-files", "--disable-background-timer-throttling",
                          "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows",
                          "--enable-unsafe-swiftshader", "about:blank"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         **({"creationflags": 0x00000008 | 0x00000200} if sys.platform == "win32" else {"start_new_session": True}))
        alvo = None
        for _ in range(240):   # até 60 s: com a máquina ocupada o Edge demora a abrir
            try:
                abas = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{self.porta}/json", timeout=1).read())
                alvo = next((x for x in abas if x.get("type") == "page" and x.get("url") == "about:blank"), None)
                if alvo:
                    break
            except Exception:
                pass
            time.sleep(0.25)
        if not alvo:
            raise RuntimeError("Edge não abriu a porta")
        self.ws = websocket.create_connection(alvo["webSocketDebuggerUrl"], suppress_origin=True, timeout=60)
        self.n, self.eventos = 0, []
        for m in ("Runtime.enable", "Page.enable", "Log.enable"):
            self.cmd(m)
        self.tamanho(self.w, self.h)
        return self

    def __exit__(self, *a):
        try:
            self.cmd("Browser.close")
        except Exception:
            pass
        time.sleep(0.6)
        if sys.platform != "win32":
            subprocess.run(["pkill", "-f", f"edgepaoli{self.marca}"], capture_output=True)
            shutil.rmtree(self.perfil, ignore_errors=True)
            return
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | Where-Object {{ $_.CommandLine -like '*edgepaoli{self.marca}*' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}"],
                       capture_output=True)
        shutil.rmtree(self.perfil, ignore_errors=True)

    def cmd(self, metodo, **params):
        self.n += 1
        meu = self.n
        self.ws.send(json.dumps({"id": meu, "method": metodo, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == meu:
                if "error" in msg:
                    raise RuntimeError(f"{metodo}: {msg['error']}")
                return msg.get("result", {})
            self.eventos.append(msg)

    def esperar(self, segundos):
        fim = time.time() + segundos
        self.ws.settimeout(0.2)
        while time.time() < fim:
            try:
                self.eventos.append(json.loads(self.ws.recv()))
            except Exception:
                pass
        self.ws.settimeout(60)

    def tamanho(self, w, h):
        self.w, self.h = w, h
        self.cmd("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=self.escala, mobile=w < 600)

    def ir(self, url, espera=2.5):
        self.cmd("Page.navigate", url=url)
        self.esperar(espera)

    def js(self, expr, espera=0.0):
        r = self.cmd("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        if r.get("exceptionDetails"):
            d = r["exceptionDetails"]
            raise RuntimeError("JS falhou: " + (d.get("exception", {}).get("description") or d.get("text", ""))[:500])
        if espera:
            self.esperar(espera)
        return r.get("result", {}).get("value")

    def clicar(self, x, y):
        # Clique "de verdade" (mouse), para componentes que ignoram click() sintético.
        for t in ("mousePressed", "mouseReleased"):
            self.cmd("Input.dispatchMouseEvent", type=t, x=x, y=y, button="left", clickCount=1)

    def foto(self, saida, inteira=False, max_h=16000):
        if inteira:
            alt = min(self.js("document.documentElement.scrollHeight"), max_h)
            w0, h0 = self.w, self.h
            self.tamanho(w0, alt)
            self.esperar(1.0)
        img = self.cmd("Page.captureScreenshot", format="png")
        with open(saida, "wb") as f:
            f.write(base64.b64decode(img["data"]))
        if inteira:
            self.tamanho(w0, h0)
            self.esperar(0.4)
        return saida

    def erros(self):
        out = []
        for e in self.eventos:
            if e.get("method") == "Runtime.exceptionThrown":
                d = e["params"]["exceptionDetails"]
                out.append("EXCECAO: " + (d.get("exception", {}).get("description") or d.get("text", ""))[:400])
            elif e.get("method") == "Runtime.consoleAPICalled" and e["params"].get("type") == "error":
                out.append("console.error: " + " ".join(str(x.get("value", x.get("description", ""))) for x in e["params"]["args"])[:400])
            elif e.get("method") == "Log.entryAdded" and e["params"]["entry"].get("level") == "error":
                txt = e["params"]["entry"].get("text", "")
                if "favicon" not in txt:
                    out.append("log: " + txt[:300])
        return out
