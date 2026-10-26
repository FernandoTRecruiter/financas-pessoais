# -*- coding: utf-8 -*-
"""
teste_financas.py: bateria do app de finanças (Edge ou Chrome headless por CDP).

Cada item imprime "OK n. ..." ou "FALHA n. ..." com o número que decidiu. O que prova:
   1. a primeira visita oferece "ver com exemplo" ou "começar do zero"
   2. o exemplo carrega a Ana (3 meses) com a faixa de exemplo à vista
   3. "Hoje dá para gastar" bate com a conta refeita AQUI a partir dos dados salvos
   4. lançar com 2 gestos (valor + categoria, com toques de mouse de verdade) e o número do
      topo cair exatamente o valor dividido pelos dias que faltam
   5. Desfazer devolve o estado inteiro
   6. OK sem categoria usa a categoria sugerida (a marcada)
   7. "+ detalhes" lança com data de ontem e descrição
   8. editar pela lista;  9. apagar pela lista (e Desfazer devolve)
  10. Mês: a faixa soma igual à lista, dia a dia e por categoria; limite passado fica coral
  11. trocar de mês
  12. calculadora comum;  13. parcelas (Price com e sem juros) contra conta feita à mão
  14. importar o CSV de exemplos/ e importar de novo sem duplicar
  15. backup exporta e restaura igual;  16. persistência depois de recarregar
  17. tema escuro;  18. celular 390 x 844 (nada vaza, toques de 44 px, teclado e barra sem rolar)
  19. nenhum travessão (nem "undefined"/"NaN") em texto;  20. dados do app antigo migram
  21. nenhum erro de JavaScript
  Rodada 2: entrada extra sobe o topo exatamente valor / dias; Histórico (cada atalho de data,
  personalizado, busca, tipo, categoria, Limpar e "Mostrar mais") contra o filtro feito aqui;
  lerNotinha com 4 notinhas escritas aqui; a notinha de ponta a ponta (imagem feita com PIL,
  leitor do CDN; sem rede vira "PULADO"); contraste AA medido no claro e no escuro.
  Rodada 4: primeiro acesso (completo, pular no passo 2, exemplo, refazer); barra com Hoje no centro;
  a tela Hoje mostra pergunta, "Fotografar nota" e categorias sem rolar; parcelas (12 meses contra a
  conta feita aqui, e "Adicionar" passa a contar no topo); marca e ícone da aba; nenhum rosa.
  Rodada 3 (aparência): nenhum emoji no texto; uma família de fonte (a serifada só no número
  grande); nenhum <select> visível; no máximo 4 elementos com fundo rosé na tela Hoje.
Rodar: pip install websocket-client  e depois  python tests/teste_financas.py
       python tests/teste_financas.py --fotos   (também regrava os prints de docs/)
(sai com código 1 se algo falhar)
"""
import calendar, csv, datetime, json, math, os, pathlib, re, sys, tempfile, unicodedata
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))
from cdp_util import Edge

RAIZ = pathlib.Path(__file__).resolve().parent.parent
URL = (RAIZ / "index.html").as_uri()
CSV = RAIZ / "exemplos" / "extrato-exemplo.csv"
DOCS = RAIZ / "docs"
TELAS = ["hoje", "mes", "hist", "calc", "ajustes"]
TRAVESSAO = chr(0x2014)
falhas = []
n_item = [0]


def checa(nome, cond, detalhe=""):
    n_item[0] += 1
    print(("OK    " if cond else "FALHA ") + f"{n_item[0]}. {nome}" + (f"  [{detalhe}]" if detalhe else ""))
    if not cond:
        falhas.append(f"{n_item[0]}. {nome}")


def arred(x):
    """Arredonda como o Math.round do JavaScript (0,5 sobe), não como o round do Python."""
    return math.floor(x + 0.5)


def brl(cent):
    """Mesmo formato do app: R$ 1.234,56 (negativo com o sinal na frente)."""
    s = f"{abs(cent) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if cent < 0 else "") + "R$ " + s


def limpo(t):
    return (t or "").replace("\xa0", " ")


def estado(ed):
    return ed.js("JSON.parse(localStorage.getItem('OF_v1'))")


def abrir_limpo(ed, tema="claro"):
    """Navegador sem nada salvo: a primeira visita de verdade (abre as boas-vindas)."""
    ed.ir(URL + "?tema=" + tema, espera=1.2)
    ed.js("localStorage.clear(); location.hash = ''; location.reload()")
    ed.esperar(2.0)


def entrar_demo(ed, tema="claro"):
    abrir_limpo(ed, tema)
    ed.js("document.getElementById('bv-demo').click()", espera=0.8)


def tela(ed, nome):
    ed.js(f"location.hash = '#{nome}'", espera=0.5)


def tocar(ed, seletor, espera=0.12):
    """Toque de verdade (mouse do CDP) no meio do elemento, depois de trazê-lo para a tela."""
    x, y = ed.js("(() => { const e = document.querySelector(" + json.dumps(seletor) + "); e.scrollIntoView({block: 'center'});"
                 " const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()")
    ed.clicar(x, y)
    ed.esperar(espera)


def digitar_em(ed, teclado, texto):
    """Digita num teclado do app (o do Hoje ou o do primeiro acesso), tecla por tecla."""
    for k in texto:
        tocar(ed, f'{teclado} [data-k="{k}"]', 0.03)


def digitar(ed, texto):
    """Digita no teclado da tela Hoje, tecla por tecla (o primeiro gesto)."""
    for k in texto:
        tocar(ed, f'#teclado [data-k="{k}"]', 0.03)


def topo(ed):
    return ed.js("(() => { const e = document.getElementById('hoje-valor'); return e.dataset.centavos === undefined ? null : +e.dataset.centavos; })()")


def conta_hoje(s, hoje):
    """A conta do topo refeita aqui, sem o código do app:
    (renda + entradas extras - contas fixas - gasto variável do mês) / dias que faltam, contando hoje.
    Entrada extra = toda entrada do mês fora da categoria Salário (o Salário já é a renda)."""
    ym = hoje.strftime("%Y-%m")
    gasto = sum(-t["v"] for t in s["tx"] if t["d"][:7] == ym and t["v"] < 0 and t["cat"] != "fixas")
    extras = sum(t["v"] for t in s["tx"] if t["d"][:7] == ym and t["v"] > 0 and t["cat"] != "salario")
    restante = s["config"]["renda"] + extras - sum(f["v"] for f in s["fixas"]) - parcelas_do_mes(s.get("parcelas", []), ym) - gasto
    dias = calendar.monthrange(hoje.year, hoje.month)[1] - hoje.day + 1
    return restante, dias, arred(restante / dias)


def meses_entre(a, b):
    """Quantos meses de a ("aaaa-mm") até b."""
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7])


def mais_meses(ym, n):
    """ym + n meses, em "aaaa-mm"."""
    total = int(ym[:4]) * 12 + int(ym[5:7]) - 1 + n
    return f"{total // 12}-{total % 12 + 1:02d}"


def parcelas_do_mes(parcelas, ym):
    """Quanto as parcelas tomam do mês: a k-ésima cai em inicio + k - 1 (refeito aqui, sem o app)."""
    return sum(x["v"] for x in parcelas if 0 <= meses_entre(x["inicio"], ym) < x["n"])


def resumo(s, ym):
    do_mes = [t for t in s["tx"] if t["d"][:7] == ym]
    entrou = sum(t["v"] for t in do_mes if t["v"] > 0)
    saiu = sum(-t["v"] for t in do_mes if t["v"] < 0)
    return entrou, saiu, entrou - saiu, do_mes


def linhas_do_csv():
    """O extrato de exemplo lido aqui: pula o resumo do topo, devolve (data, valor em centavos)."""
    linhas = list(csv.reader(CSV.read_text(encoding="utf-8").splitlines(), delimiter=";"))
    i = next(k for k, l in enumerate(linhas) if l and l[0] == "RELEASE_DATE")
    return [(l[0], round(float(l[3].replace(".", "").replace(",", ".")) * 100)) for l in linhas[i + 1:] if len(l) >= 4 and l[0].strip()]


def norm(s):
    """Minúsculas e sem acento, como o normal() do app (para a busca do Histórico)."""
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn").strip()


def hist_esperado(s, de, ate, q="", tipo="todos", cat="todas"):
    """O filtro do Histórico refeito aqui: [entrou, saiu, saldo, quantos]."""
    cats = {c["id"]: c for c in s["cats"]}
    def cat_de(t):
        return t["cat"] if t["cat"] in cats else ("outras-entradas" if t["v"] > 0 else "outros")
    sel = [t for t in s["tx"] if (not de or t["d"] >= de) and (not ate or t["d"] <= ate)
           and (tipo == "todos" or (tipo == "g") == (t["v"] < 0)) and (cat == "todas" or cat_de(t) == cat)
           and (not q or norm(q) in norm(t["desc"]) or norm(q) in norm(cats[cat_de(t)]["nome"]))]
    entrou = sum(t["v"] for t in sel if t["v"] > 0)
    saiu = sum(-t["v"] for t in sel if t["v"] < 0)
    return [entrou, saiu, entrou - saiu, len(sel)]


def notinha_png(data):
    """Uma notinha limpa desenhada aqui (fonte monoespaçada), para o leitor de ponta a ponta."""
    from PIL import Image, ImageDraw, ImageFont
    linhas = ["PADARIA DOCE LAR", "CNPJ 12.345.678/0001-90", "RUA DAS FLORES, 100", "", "PAO FRANCES        12,40",
              "BOLO DE FUBA       25,00", "CAFE COADO         50,05", "", "TOTAL R$           87,45", "", data.strftime("%d/%m/%Y") + " 08:15"]
    try:
        fonte = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 40)
    except OSError:
        fonte = ImageFont.load_default(size=40)
    img = Image.new("RGB", (760, 120 + 58 * len(linhas)), "white")
    d = ImageDraw.Draw(img)
    for i, l in enumerate(linhas):
        d.text((50, 60 + 58 * i), l, fill="black", font=fonte)
    caminho = os.path.join(tempfile.gettempdir(), f"notinha_teste_{os.getpid()}.png")
    img.save(caminho)
    return caminho


def cor(valor, base=(255, 255, 255)):
    """'#RRGGBB' ou 'rgba(r, g, b, a)' vira (r, g, b); a transparente é misturada com a base."""
    valor = valor.strip()
    if valor.startswith("#"):
        return tuple(int(valor[i:i + 2], 16) for i in (1, 3, 5))
    partes = [float(x) for x in valor[valor.index("(") + 1:-1].split(",")]
    a = partes[3] if len(partes) > 3 else 1
    return tuple(round(partes[i] * a + base[i] * (1 - a)) for i in range(3))


def eh_rosa(valor):
    """Cor computada (rgb/rgba) na faixa do rosa ou magenta: matiz de 300 a 360 ou de 0 a 15 graus,
    saturação (HSL) acima de 25%. Transparente não conta."""
    import colorsys
    partes = [float(x) for x in valor[valor.index("(") + 1:-1].split(",")]
    if len(partes) > 3 and partes[3] == 0:
        return False
    hh, ll, ss = colorsys.rgb_to_hls(*(x / 255 for x in partes[:3]))
    graus = hh * 360
    return ss > 0.25 and (graus >= 300 or graus <= 15) and max(partes[:3]) - min(partes[:3]) > 8


def contraste(a, b):
    """Razão de contraste da WCAG entre duas cores (r, g, b)."""
    def lum(c):
        def canal(x):
            x /= 255
            return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
        r, g, b_ = (canal(x) for x in c)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b_
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)

def arquivo(ed, seletor, caminho):
    """Escolhe um arquivo num <input type=file>, como a pessoa faria na janela do sistema."""
    raiz = ed.cmd("DOM.getDocument")["root"]["nodeId"]
    no = ed.cmd("DOM.querySelector", nodeId=raiz, selector=seletor)["nodeId"]
    ed.cmd("DOM.setFileInputFiles", files=[str(caminho)], nodeId=no)
    ed.esperar(1.0)


hoje = datetime.date.today()
ontem = hoje - datetime.timedelta(days=1)
ym = hoje.strftime("%Y-%m")
textos = []   # todo texto visível visto na bateria (o item 19 procura travessão nele)

with Edge(390, 844) as ed:
    # 1. primeira visita
    abrir_limpo(ed)
    r = ed.js("({aberta: !document.getElementById('primeiro').hidden, comecar: !!document.getElementById('pa-comecar'),"
              " demo: !!document.getElementById('bv-demo'), pular: !!document.getElementById('pa-pular'),"
              " passo: document.getElementById('pa-indicador').dataset.passo, logo: (document.querySelector('#primeiro .logo-nome') || {}).textContent,"
              " icone: document.querySelector('link[rel=\"icon\"]').href, texto: document.body.innerText})")
    textos.append(r["texto"])
    checa("primeira visita abre o passo a passo (1 de 4) com Começar, 'Só quero ver um exemplo' e Pular",
          r["aberta"] and r["comecar"] and r["demo"] and r["pular"] and r["passo"] == "1", str({k: v for k, v in r.items() if k != "texto"})[:200])
    checa("marca: logotipo 'Vintém' na abertura e o ícone da aba é a mesma marca (SVG)",
          r["logo"] == "Vintém" and r["icone"].startswith("data:image/svg+xml") and "circle" in r["icone"] and "965A38" in r["icone"], r["icone"][:80])

    # primeiro acesso completo: renda pelo teclado do app, uma conta fixa por chip e uma parcela
    tocar(ed, "#pa-comecar", 0.3)
    digitar_em(ed, "#pa-teclado", "5000")
    tocar(ed, "#pa-ok", 0.3)
    passo3 = ed.js("document.getElementById('pa-indicador').dataset.passo")
    tocar(ed, '[data-sug="Aluguel"]', 0.3)
    ed.js("(() => { const i = document.getElementById('pa-fixa-valor'); i.value = '1.500,00'; })()")
    tocar(ed, "#pa-fixa-add", 0.3)
    tocar(ed, "#pa-continuar", 0.3)
    ed.js("(() => { const v = {'pa-parc-nome': 'Notebook', 'pa-parc-valor': '250,00', 'pa-parc-faltam': '6'};"
          " Object.keys(v).forEach(k => document.getElementById(k).value = v[k]); })()")
    tocar(ed, "#pa-parc-add", 0.3)
    tocar(ed, "#pa-pronto", 0.6)
    s_pa = estado(ed)
    r_pa = ed.js("({fechou: document.getElementById('primeiro').hidden, tela: !document.getElementById('tela-hoje').hidden})")
    checa("primeiro acesso completo: renda, conta fixa e parcela gravadas e o 'Hoje dá para gastar' sai certo",
          passo3 == "3" and s_pa["config"]["renda"] == 500000 and [(f["nome"], f["v"]) for f in s_pa["fixas"]] == [("Aluguel", 150000)]
          and [(x["nome"], x["v"], x["n"], x["inicio"]) for x in s_pa["parcelas"]] == [("Notebook", 25000, 6, ym)]
          and r_pa["fechou"] and r_pa["tela"] and topo(ed) == conta_hoje(s_pa, hoje)[2],
          f"renda {s_pa['config']['renda']}, fixas {s_pa['fixas']}, parcelas {s_pa['parcelas']}, topo {topo(ed)} x conta {conta_hoje(s_pa, hoje)}")

    # pular no passo 2 grava a renda já digitada e segue para o passo 3
    abrir_limpo(ed)
    tocar(ed, "#pa-comecar", 0.3)
    digitar_em(ed, "#pa-teclado", "4000")
    tocar(ed, "#pa-pular", 0.3)
    r_pu = ed.js("({passo: document.getElementById('pa-indicador').dataset.passo, aberto: !document.getElementById('primeiro').hidden})")
    renda_pulo = estado(ed)["config"]["renda"]
    tocar(ed, "#pa-pular", 0.3)
    tocar(ed, "#pa-pular", 0.5)
    fechou_pulando = ed.js("document.getElementById('primeiro').hidden")
    # refazer pelos Ajustes abre o passo a passo de novo
    tela(ed, "ajustes")
    tocar(ed, "#aj-refazer", 0.4)
    refez = ed.js("!document.getElementById('primeiro').hidden && document.getElementById('pa-indicador').dataset.passo === '1'")
    tocar(ed, "#pa-pular", 0.4)
    checa("Pular no passo 2 grava a renda e segue; 'Refazer o primeiro acesso' nos Ajustes abre de novo",
          renda_pulo == 400000 and r_pu["passo"] == "3" and r_pu["aberto"] and fechou_pulando and refez
          and ed.js("document.getElementById('primeiro').hidden"), f"renda {renda_pulo}, {r_pu}, fechou {fechou_pulando}, refez {refez}")
    abrir_limpo(ed)

    # 2. exemplo
    ed.js("document.getElementById('bv-demo').click()", espera=0.8)
    s = estado(ed)
    meses = sorted({t["d"][:7] for t in s["tx"]})
    r = ed.js("({faixa: !document.getElementById('faixa-demo').hidden, folha: document.getElementById('folha').open || !document.getElementById('primeiro').hidden,"
              " ultimos: document.querySelectorAll('#ultimos .item').length})")
    checa("'Só quero ver um exemplo': a Ana com 3 meses, 2 parcelas (faltam 4 de 10 e 7 de 12) e a faixa de exemplo",
          s["config"]["demo"] and len(meses) == 3 and len(s["tx"]) > 90 and r["faixa"] and not r["folha"] and r["ultimos"] == 2
          and [(x["nome"], x["v"], meses_entre(x["inicio"], ym), x["n"]) for x in s["parcelas"]] == [("Celular novo", 18900, 6, 10), ("Geladeira", 24000, 5, 12)],
          f"{len(s['tx'])} lançamentos em {meses}, {r}")

    ordem = ed.js("[...document.querySelectorAll('#nav a')].map(a => a.dataset.tela)")
    ed.ir(URL, espera=1.5)
    abre = ed.js("({tela: !document.getElementById('tela-hoje').hidden, atual: document.querySelector('#nav a[aria-current]').dataset.tela,"
                 " centro: document.querySelector('#nav a.centro').dataset.tela})")
    checa("barra: Histórico, Mês, Hoje, Calcular, Ajustes, com Hoje no centro; o app abre em Hoje",
          ordem == ["hist", "mes", "hoje", "calc", "ajustes"] and abre["tela"] and abre["atual"] == "hoje" and abre["centro"] == "hoje", f"{ordem} {abre}")

    # 3. o número do topo bate com a conta feita aqui
    restante, dias, por_dia = conta_hoje(s, hoje)
    texto_topo = limpo(ed.js("document.getElementById('hoje-valor').textContent"))
    ed.esperar(0.6)
    texto_topo = limpo(ed.js("document.getElementById('hoje-valor').textContent"))
    checa("'Hoje dá para gastar' = (renda + extras - fixas - gasto variável) / dias que faltam",
          topo(ed) == por_dia and texto_topo == brl(por_dia) and restante > 0,
          f"tela {topo(ed)} ({texto_topo}) x conta {restante} / {dias} = {por_dia}")

    # 4. lançar com 2 gestos: o valor (teclas) e UM toque na categoria
    valor = dias * 235                  # múltiplo dos dias: a queda do topo tem de ser exatamente R$ 2,35
    texto_valor = f"{valor // 100},{valor % 100:02d}"
    antes_json = json.dumps(s, sort_keys=True)
    antes_topo = topo(ed)
    digitar(ed, texto_valor)
    visor = limpo(ed.js("document.getElementById('visor').textContent"))
    tocar(ed, '#cats [data-cat="mercado"]', 0.3)
    s4 = estado(ed)
    ult = s4["tx"][-1]
    toast = ed.js("({v: document.getElementById('toast').classList.contains('visivel'), t: document.getElementById('toast').innerText})")
    queda = antes_topo - topo(ed)
    checa("lançar com 2 gestos (valor + categoria) e o topo cai exatamente valor / dias",
          len(s4["tx"]) == len(s["tx"]) + 1 and ult["v"] == -valor and ult["cat"] == "mercado" and ult["d"] == hoje.isoformat()
          and queda == valor // dias == 235 and toast["v"] and "Desfazer" in toast["t"] and topo(ed) == conta_hoje(s4, hoje)[2],
          f"visor {visor!r}, {ult['v']} em {ult['cat']}, topo {antes_topo} -> {topo(ed)} (caiu {queda}), aviso {limpo(toast['t'])!r}")

    # 5. Desfazer devolve o estado inteiro
    tocar(ed, "#toast button", 0.3)
    s5 = estado(ed)
    checa("Desfazer devolve o estado de antes (inteiro) e o número do topo",
          json.dumps(s5, sort_keys=True) == antes_json and topo(ed) == antes_topo, f"{len(s5['tx'])} lançamentos, topo {topo(ed)}")

    # 5b. uma entrada extra (fora de Salário) sobe o número do topo exatamente valor / dias
    antes_extra = topo(ed)
    tocar(ed, '#tipo-sel [data-tipo="e"]')
    digitar(ed, texto_valor)
    tocar(ed, '#cats [data-cat="extra"]', 0.3)
    s5b = estado(ed)
    subiu = topo(ed) - antes_extra
    checa("entrada extra lançada sobe o 'Hoje dá para gastar' exatamente valor / dias",
          s5b["tx"][-1]["v"] == valor and s5b["tx"][-1]["cat"] == "extra" and subiu == 235 and topo(ed) == conta_hoje(s5b, hoje)[2],
          f"topo {antes_extra} -> {topo(ed)} (subiu {subiu})")
    tocar(ed, "#toast button", 0.3)


    # 6. OK sem categoria usa a sugerida
    digitar(ed, "7")
    sugerida = ed.js("document.querySelector('#cats [aria-pressed=\"true\"]').dataset.cat")
    tocar(ed, "#tecla-ok", 0.3)
    s6 = estado(ed)
    checa("OK sem categoria lança na categoria sugerida (a marcada)",
          len(s6["tx"]) == len(s5["tx"]) + 1 and s6["tx"][-1]["cat"] == sugerida and s6["tx"][-1]["v"] == -700,
          f"sugerida {sugerida}, lançado em {s6['tx'][-1]['cat']}")
    tocar(ed, "#toast button", 0.3)

    # 7. "+ detalhes": ontem e descrição
    tocar(ed, "#btn-detalhes")
    tocar(ed, '#quando [data-q="ontem"]')
    ed.js("(() => { const i = document.getElementById('det-desc'); i.value = 'Presente da Bia'; i.dispatchEvent(new Event('input')); })()")
    digitar(ed, "45")
    tocar(ed, '#cats [data-cat="compras"]', 0.3)
    s7 = estado(ed)
    u7 = s7["tx"][-1]
    fechou = ed.js("document.getElementById('detalhes').hidden")
    checa("'+ detalhes' lança com data de ontem e descrição, e fecha depois",
          u7["d"] == ontem.isoformat() and u7["desc"] == "Presente da Bia" and u7["v"] == -4500 and u7["cat"] == "compras" and fechou,
          str(u7))
    tocar(ed, "#toast button", 0.3)

    # 8. editar pela lista de hoje
    alvo = ed.js("document.querySelector('#ultimos .item').dataset.id")
    tocar(ed, "#ultimos .item", 0.4)
    aberta = ed.js("document.getElementById('folha').open")
    ed.js("(() => { const i = document.getElementById('ed-valor'); i.value = '99,99'; i.dispatchEvent(new Event('input')); })()")
    tocar(ed, '#ed-cats [data-cat="lazer"]')
    tocar(ed, "#ed-salvar", 0.4)
    s8 = estado(ed)
    t8 = next(t for t in s8["tx"] if t["id"] == alvo)
    checa("editar pela lista: tocar abre, mudar valor e categoria e salvar grava",
          aberta and t8["v"] == -9999 and t8["cat"] == "lazer" and topo(ed) == conta_hoje(s8, hoje)[2]
          and not ed.js("document.getElementById('folha').open"), f"{t8}")

    # 9. apagar pela lista (e Desfazer devolve); o aviso de antes sai da frente, como quem espera ele sumir
    ed.js("esconderToast()", espera=0.3)
    tocar(ed, f'#ultimos .item[data-id="{alvo}"]', 0.4)
    tocar(ed, "#ed-apagar", 0.4)
    s9 = estado(ed)
    sumiu = not any(t["id"] == alvo for t in s9["tx"])
    tocar(ed, "#toast button", 0.3)
    voltou = any(t["id"] == alvo for t in estado(ed)["tx"])
    checa("apagar pela lista tira o lançamento; Desfazer devolve", sumiu and voltou and len(s9["tx"]) == len(s8["tx"]) - 1)

    # 10. Mês: faixa, lista, dia a dia e categorias somam igual
    s10 = estado(ed)
    tela(ed, "mes")
    entrou, saiu, sobra, do_mes = resumo(s10, ym)
    m = ed.js("(() => { const k = c => +document.querySelector('[data-kpi=\"' + c + '\"]').dataset.centavos;"
              " const itens = [...document.querySelectorAll('#tela-mes .dia .item')].map(e => +e.dataset.centavos);"
              " const dias = [...document.querySelectorAll('#tela-mes .dia')].map(e => +e.dataset.centavos);"
              " const cats = [...document.querySelectorAll('#mes-cats [data-cat]')].map(e => [e.dataset.cat, +e.dataset.centavos, e.classList.contains('passou')]);"
              " return {entrou: k('entrou'), saiu: k('saiu'), sobra: k('sobra'), itens, dias, cats, texto: document.body.innerText}; })()")
    textos.append(m["texto"])
    gasto_cat = {}
    for t in do_mes:
        if t["v"] < 0:
            gasto_cat[t["cat"]] = gasto_cat.get(t["cat"], 0) - t["v"]
    limites = {c["id"]: c.get("limite", 0) for c in s10["cats"]}
    coral_ok = all(p == (limites.get(c, 0) > 0 and v > limites.get(c, 0)) for c, v, p in m["cats"] if c != "fixas")
    passaram = [c for c, v, p in m["cats"] if p]
    checa("Mês: entrou, saiu e sobra batem com a lista, com o dia a dia e com as categorias",
          (m["entrou"], m["saiu"], m["sobra"]) == (entrou, saiu, sobra) and len(m["itens"]) == len(do_mes)
          and sum(m["itens"]) == sobra and sum(m["dias"]) == sobra and sum(v for _, v, _ in m["cats"]) == saiu
          and {c: v for c, v, _ in m["cats"]} == gasto_cat,
          f"tela {(m['entrou'], m['saiu'], m['sobra'])} x conta {(entrou, saiu, sobra)}; {len(m['itens'])} itens x {len(do_mes)}")
    checa("Mês: a barra fica coral só na categoria que passou do limite", coral_ok, f"passaram: {passaram}")

    # 11. trocar de mês
    antes_ym = (hoje.replace(day=1) - datetime.timedelta(days=1)).strftime("%Y-%m")
    prox_desligado = ed.js("document.getElementById('mes-prox').disabled")
    tocar(ed, "#mes-ant", 0.3)
    e2, s2_, so2, dm2 = resumo(s10, antes_ym)
    m2 = ed.js("({ym: document.getElementById('mes-titulo').dataset.ym, sobra: +document.querySelector('[data-kpi=\"sobra\"]').dataset.centavos,"
               " n: document.querySelectorAll('#tela-mes .dia .item').length, prox: document.getElementById('mes-prox').disabled})")
    tocar(ed, "#mes-prox", 0.3)
    volta = ed.js("document.getElementById('mes-titulo').dataset.ym")
    checa("trocar de mês: a seta volta um mês com os números dele e a outra seta traz de volta",
          prox_desligado and m2["ym"] == antes_ym and m2["sobra"] == so2 and m2["n"] == len(dm2) and not m2["prox"] and volta == ym,
          f"{m2}, voltou para {volta}")

    # Histórico: cada atalho de data dá a mesma soma que o filtro feito aqui
    s_h = estado(ed)
    tela(ed, "hist")
    textos.append(ed.js("document.body.innerText"))

    def hist_tela():
        return ed.js("(() => { const k = c => +document.querySelector('[data-kpi=\"' + c + '\"]').dataset.centavos;"
                     " return [k('h-entrou'), k('h-saiu'), k('h-saldo'), +document.getElementById('hist-n').dataset.n]; })()")
    ultimo_mes = calendar.monthrange(hoje.year, hoje.month)[1]
    passado = hoje.replace(day=1) - datetime.timedelta(days=1)
    faixas = {"tudo": ("", ""), "7d": ((hoje - datetime.timedelta(days=6)).isoformat(), hoje.isoformat()),
              "30d": ((hoje - datetime.timedelta(days=29)).isoformat(), hoje.isoformat()),
              "mes": (f"{ym}-01", f"{ym}-{ultimo_mes:02d}"),
              "passado": (passado.replace(day=1).isoformat(), passado.isoformat()),
              "ano": (f"{hoje.year}-01-01", f"{hoje.year}-12-31")}
    erradas = []
    for periodo, (de, ate) in faixas.items():
        ed.js(f"document.querySelector('#hist-periodos [data-v=\"{periodo}\"]').click()", espera=0.2)
        tela_h, conta_h = hist_tela(), hist_esperado(s_h, de, ate)
        if tela_h != conta_h:
            erradas.append(f"{periodo}: tela {tela_h} x conta {conta_h}")
    checa("Histórico: Tudo, 7 dias, 30 dias, este mês, mês passado e este ano somam igual ao filtro feito aqui",
          not erradas, "; ".join(erradas))
    de_p, ate_p = (hoje - datetime.timedelta(days=20)).isoformat(), (hoje - datetime.timedelta(days=10)).isoformat()
    ed.js("document.querySelector('#hist-periodos [data-v=\"pers\"]').click()", espera=0.2)
    ed.js(f"(() => {{ const a = document.getElementById('hist-de'), b = document.getElementById('hist-ate'); a.value = '{de_p}'; a.dispatchEvent(new Event('change'));"
          f" b.value = '{ate_p}'; b.dispatchEvent(new Event('change')); }})()", espera=0.2)
    pers_tela, pers_conta = hist_tela(), hist_esperado(s_h, de_p, ate_p)
    ed.js("(() => { const q = document.getElementById('hist-q'); q.value = 'uber'; q.dispatchEvent(new Event('input')); })()", espera=0.2)
    busca_tela, busca_conta = hist_tela(), hist_esperado(s_h, de_p, ate_p, q="uber")
    ativo = ed.js("({v: !document.getElementById('hist-ativo').hidden, t: document.getElementById('hist-ativo-txt').textContent})")
    tocar(ed, "#hist-limpar", 0.3)
    limpo_tela, limpo_conta = hist_tela(), hist_esperado(s_h, "", "")
    checa("Histórico: personalizado de/até e busca batem; o filtro aparece escrito e 'Limpar' volta ao total",
          pers_tela == pers_conta and busca_tela == busca_conta and busca_conta[3] > 0 and ativo["v"] and "uber" in ativo["t"]
          and limpo_tela == limpo_conta and ed.js("document.getElementById('hist-ativo').hidden"),
          f"pers {pers_tela}/{pers_conta}, busca {busca_tela}/{busca_conta}, limpar {limpo_tela}/{limpo_conta}, {ativo['t']!r}")
    tocar(ed, '#hist-tipos [data-v="g"]', 0.2)
    tocar(ed, '#hist-cats [data-v="mercado"]', 0.2)
    gm_tela, gm_conta = hist_tela(), hist_esperado(s_h, "", "", tipo="g", cat="mercado")
    tocar(ed, "#hist-limpar", 0.3)
    n_desenhados = ed.js("document.querySelectorAll('#hist-resultado .item').length")
    tem_mais = ed.js("!!document.getElementById('hist-mais')")
    if tem_mais:
        ed.js("document.getElementById('hist-mais').click()", espera=0.3)
    n_todos = ed.js("document.querySelectorAll('#hist-resultado .item').length")
    checa("Histórico: tipo + categoria batem, e a lista longa vem em blocos de 80 com 'Mostrar mais'",
          gm_tela == gm_conta and gm_conta[3] > 0 and n_desenhados == min(80, len(s_h["tx"])) and tem_mais == (len(s_h["tx"]) > 80)
          and n_todos == min(160, len(s_h["tx"])), f"gastos de mercado {gm_tela}/{gm_conta}, desenhados {n_desenhados} -> {n_todos} de {len(s_h['tx'])}")


    # 12. calculadora comum
    tela(ed, "calc")
    textos.append(ed.js("document.body.innerText"))

    def teclas(seq):
        return ed.js("(() => { " + "".join(f"document.querySelector('[data-tecla=\"{k}\"]').click();" for k in seq) +
                     " return document.getElementById('calc-visor').textContent; })()")
    contas = {"C12+3×2=": "30", "C10÷4=": "2,5", "C50+10%=": "55", "C1÷0=": "Não dá para dividir por zero", "C0,1+0,2=": "0,3"}
    erradas = [f"{seq} deu {teclas(seq)!r}" for seq, esp in contas.items() if teclas(seq) != esp]
    pelo_teclado = ed.js("(() => { ['Escape', '7', '*', '6', 'Enter'].forEach(k => document.body.dispatchEvent("
                         "new KeyboardEvent('keydown', {key: k, bubbles: true}))); return document.getElementById('calc-visor').textContent; })()")
    checa("calculadora: 12+3×2=30, 10÷4=2,5, 50+10%=55, 0,1+0,2=0,3, ÷0 avisa e o teclado faz 7×6=42",
          not erradas and pelo_teclado == "42", "; ".join(erradas) + f" teclado {pelo_teclado!r}")

    # 13. parcelas contra a conta feita à mão
    tocar(ed, "#calc-aba-parcelas", 0.3)
    textos.append(ed.js("document.body.innerText"))

    def parcelas(preco, n, juros, desc, rend):
        ed.js("(() => { const v = " + json.dumps({"preco": preco, "n": n, "juros": juros, "desc": desc, "rend": rend}) + ";"
              " Object.keys(v).forEach(k => { const i = document.getElementById('parc-' + k); i.value = v[k]; i.dispatchEvent(new Event('input')); }); })()", espera=0.2)
        return ed.js("(() => { const c = id => +document.getElementById(id).dataset.centavos;"
                     " return {parcela: c('parc-parcela'), total: c('parc-total'), amais: c('parc-amais'), avista: c('parc-avista'),"
                     " frase: document.getElementById('parc-frase').textContent}; })()")
    # À mão (tabela Price): 1.000 × 0,02 / (1 - 1,02^-10) = 111,3265 -> R$ 111,33; total 10 × 111,33 = R$ 1.113,30;
    # a mais R$ 113,30; à vista com 5% = R$ 950,00; diferença R$ 163,30 a favor de pagar à vista.
    p1 = parcelas("1.000,00", "10", "2", "5", "0")
    f1 = limpo(p1["frase"])
    ok1 = (p1["parcela"], p1["total"], p1["amais"], p1["avista"]) == (11133, 111330, 11330, 95000) \
        and f1.startswith("À vista é melhor") and "R$ 163,30" in f1 and 11133 == arred(100000 * 0.02 / (1 - 1.02 ** -10))
    # Sem juros, 10 × R$ 100, dinheiro rendendo 0,8% ao mês: as parcelas valem hoje
    # 100 × (1 - 1,008^-10) / 0,008 = R$ 957,37, ou seja, R$ 42,63 a menos que pagar R$ 1.000 à vista.
    p2 = parcelas("1.000,00", "10", "0", "0", "0,8")
    f2 = limpo(p2["frase"])
    ok2 = (p2["parcela"], p2["total"], p2["amais"], p2["avista"]) == (10000, 100000, 0, 100000) \
        and f2.startswith("Parcelar é melhor") and "R$ 957,37" in f2 and "R$ 42,63" in f2
    checa("parcelas: Price 10x a 2% (R$ 111,33; total R$ 1.113,30) e 10x sem juros rendendo 0,8% (vale R$ 957,37)",
          ok1 and ok2, f"{p1} | {p2}")

    # notinha: a leitura do texto (função pura) com 4 notinhas escritas aqui
    tela(ed, "hoje")
    notas = [
        ("mercado com TOTAL", "SUPERMERCADO BOM PRECO LTDA\nCNPJ 11.222.333/0001-44\nAV. BRASIL, 1500 CENTRO\nCUPOM FISCAL ELETRONICO\n"
         "ARROZ 5KG 27,90\nFEIJAO 1KG 8,49\nLEITE 6,19\nSUBTOTAL 42,58\nDESCONTO 2,58\nTOTAL R$ 40,00\nDINHEIRO 50,00\nTROCO 10,00\n15/10/2026 18:42",
         {"valor": 4000, "data": "2026-10-15", "loja": "Supermercado Bom Preco"}),
        ("restaurante com VALOR A PAGAR", "Cantina da Nonna\nCNPJ: 22.333.444/0001-55\nRua Itália, 45\n2 Lasanha 89,80\n1 Suco 12,00\n"
         "Total itens 101,80\nServiço 10% 10,18\nVALOR A PAGAR 111,98\nData: 03/09/2026",
         {"valor": 11198, "data": "2026-09-03", "loja": "Cantina da Nonna"}),
        ("farmácia sem a palavra total", "DROGARIA SAUDE JA\nCNPJ 33.444.555/0001-66\nR. DAS PALMEIRAS 12\nDIPIRONA 500MG 12,90\n"
         "PROTETOR SOLAR FPS50 49,90\nPAGAMENTO CARTAO 62,80\n01/10/2026",
         {"valor": 6280, "data": "2026-10-01", "loja": "Drogaria Saude Ja"}),
        ("data dd/mm/aa", "PADARIA PAO QUENTE\nCPF/CNPJ 44.555.666/0001-77\nPAO DE QUEIJO 18,00\nCAFE 7,50\nTOTAL 25,50\nEMISSAO 05/10/26 09:10",
         {"valor": 2550, "data": "2026-10-05", "loja": "Padaria Pao Quente"}),
    ]
    erradas = []
    for nome, texto, esperado in notas:
        lido = ed.js(f"lerNotinha({json.dumps(texto)})")
        if lido != esperado:
            erradas.append(f"{nome}: {lido} (esperado {esperado})")
    checa("lerNotinha: valor, data e loja certos em 4 notinhas (TOTAL, VALOR A PAGAR, sem total, data dd/mm/aa)", not erradas, "; ".join(erradas))

    # notinha de ponta a ponta: uma imagem limpa feita aqui com PIL vai pelo botão da câmera
    nao_baixou = ed.js("!window.Tesseract && !document.querySelector('script[src*=\"tesseract\"]')")
    data_nota = hoje - datetime.timedelta(days=2)
    caminho_nota = notinha_png(data_nota)
    # grava cada texto que a faixa mostrou: o progresso passa rápido demais para uma foto a cada 0,5 s
    ed.js("window.__faixa = []; new MutationObserver(() => window.__faixa.push(document.getElementById('notinha-faixa').innerText))"
          ".observe(document.getElementById('notinha-faixa'), {childList: true, subtree: true, characterData: true})")
    arquivo(ed, "#notinha-arquivo", caminho_nota)
    viu_progresso, fim = False, None
    for _ in range(240):                     # até 120 s: na primeira vez o leitor baixa uns 10 MB
        r = ed.js("({nota: DIG.nota && DIG.nota.estado, txt: (document.getElementById('notinha-faixa') || {}).innerText || '',"
                  " v: +document.getElementById('visor').dataset.centavos, tess: !!window.Tesseract})")
        viu_progresso = viu_progresso or ed.js(r"window.__faixa.some(t => /Lendo a nota\.\.\. \d+%/.test(t))")
        if r["nota"] in ("lido", "erro"):
            fim = r
            break
        ed.esperar(0.5)
    os.unlink(caminho_nota)
    if fim is None or (fim["nota"] == "erro" and not fim["tess"]):
        n_item[0] += 1
        print(f"PULADO {n_item[0]}. notinha de ponta a ponta (sem rede: o leitor não carregou do CDN)  [{fim}]")
    else:
        lido = ed.js("({visor: document.getElementById('visor').textContent, desc: DIG.desc, data: DIG.data,"
                     " faixa: document.getElementById('notinha-faixa').innerText, cat: document.querySelector('#cats [aria-pressed=\"true\"]').dataset.cat})")
        textos.append(lido["faixa"])
        checa("notinha de ponta a ponta: a foto vira R$ 87,45 no visor, com loja, data e a faixa 'Confira os dados da nota' (sem lançar sozinho)",
              nao_baixou and viu_progresso and limpo(lido["visor"]) == "R$ 87,45" and "Padaria" in lido["desc"] and lido["data"] == data_nota.isoformat()
              and lido["faixa"].startswith("Confira os dados da nota") and lido["cat"] == "cafe" and len(estado(ed)["tx"]) == len(s_h["tx"]),
              f"{lido}, progresso visto {viu_progresso}, leitor só baixou ao tocar {nao_baixou}")
        # lançar continua sendo tocar na categoria
        tocar(ed, '#cats [data-cat="cafe"]', 0.3)
        u = estado(ed)["tx"][-1]
        checa("notinha: tocar na categoria lança o que foi lido (e a faixa some)",
              u["v"] == -8745 and u["d"] == data_nota.isoformat() and "Padaria" in u["desc"] and ed.js("document.getElementById('notinha-faixa').hidden"), str(u))
        tocar(ed, "#toast button", 0.3)


    # parcelas: ver a compra junto com as parcelas que já existem (12 meses) e transformar em parcela
    tela(ed, "calc")
    ed.js("document.getElementById('calc-aba-parcelas').click()", espera=0.3)
    s_pc = estado(ed)
    ed.js("(() => { const v = {preco: '1.200,00', n: '6', juros: '0', desc: '0', rend: '0'};"
          " Object.keys(v).forEach(k => { const i = document.getElementById('parc-' + k); i.value = v[k]; i.dispatchEvent(new Event('input')); }); })()", espera=0.2)
    tocar(ed, "#parc-ver", 0.4)
    barras = ed.js("[...document.querySelectorAll('#parc-barras .barra-mes')].map(b => [b.dataset.ym, +b.dataset.existente, +b.dataset.nova])")
    esperado = [[mais_meses(ym, i), parcelas_do_mes(s_pc["parcelas"], mais_meses(ym, i)), 20000 if i < 6 else 0] for i in range(12)]
    pior = max(e + n for _, e, n in esperado)
    frase = limpo(ed.js("document.getElementById('parc-pior').textContent"))
    pct = arred(pior / s_pc["config"]["renda"] * 100)
    textos.append(ed.js("document.body.innerText"))
    checa("parcelas: cada um dos 12 meses soma as parcelas que existem + a simulada, e a frase traz o pior mês",
          barras == esperado and f"seu pior mês fica em {brl(pior)} ({pct}% da renda)" in frase and ed.js("!!document.querySelector('#parc-grafico .limite-linha')"),
          f"tela {barras[:3]}... x conta {esperado[:3]}...; {frase!r}")
    ed.js("(() => { const i = document.getElementById('parc-nome'); i.value = 'Bicicleta'; i.dispatchEvent(new Event('input')); })()")
    tocar(ed, "#parc-adicionar", 0.4)
    s_pc2 = estado(ed)
    tela(ed, "hoje")
    nova = s_pc2["parcelas"][-1] if s_pc2["parcelas"] else {}
    checa("'Adicionar às minhas parcelas' cria a parcela e ela passa a contar no 'Hoje dá para gastar'",
          len(s_pc2["parcelas"]) == len(s_pc["parcelas"]) + 1 and (nova.get("nome"), nova.get("v"), nova.get("n"), nova.get("inicio")) == ("Bicicleta", 20000, 6, ym)
          and topo(ed) == conta_hoje(s_pc2, hoje)[2] and conta_hoje(s_pc2, hoje)[0] == conta_hoje(s_pc, hoje)[0] - 20000,
          f"{nova}, topo {topo(ed)} x conta {conta_hoje(s_pc2, hoje)}")

    # 14. importar o CSV de exemplo duas vezes (começando do zero)
    abrir_limpo(ed)
    ed.js("document.getElementById('pa-pular').click()", espera=0.5)
    tela(ed, "ajustes")
    esperadas = linhas_do_csv()

    def importar():
        ed.js("document.getElementById('btn-importar').click()", espera=0.4)
        arquivo(ed, "#imp-arquivo", CSV)
        return ed.js("({resumo: document.getElementById('imp-resumo').textContent, botao: document.getElementById('imp-confirmar').textContent,"
                     " desligado: document.getElementById('imp-confirmar').disabled, texto: document.body.innerText})")
    r1 = importar()
    textos.append(r1["texto"])
    selects_import = ed.js("document.querySelectorAll('select').length")
    ed.js("document.getElementById('imp-confirmar').click()", espera=0.5)
    s14 = estado(ed)
    soma = sum(t["v"] for t in s14["tx"])
    cats = {t["desc"]: t["cat"] for t in s14["tx"]}
    cat_ok = cats.get("Pagamento Supermercado Bom Preço") == "mercado" and cats.get("Pagamento iFood pedido") == "comida" \
        and cats.get("Transferência recebida Salário Empresa Exemplo Ltda") == "salario"
    r2 = importar()
    ed.js("document.getElementById('folha').close()", espera=0.2)
    s14b = estado(ed)
    checa("importar CSV: entra cada linha uma vez (sem o resumo do topo) e a categoria vem sugerida",
          len(s14["tx"]) == len(esperadas) and soma == sum(v for _, v in esperadas) and not r1["desligado"] and cat_ok,
          f"{len(s14['tx'])} de {len(esperadas)} linhas, soma {soma} x {sum(v for _, v in esperadas)}; {r1['resumo']}")
    checa("importar o mesmo CSV de novo: nada duplica e o botão desliga",
          len(s14b["tx"]) == len(s14["tx"]) and r2["desligado"] and f"{len(esperadas)} já existiam" in r2["resumo"],
          f"{len(s14b['tx'])} lançamentos; {r2['resumo']} / {r2['botao']}")

    # 15. backup: exporta pelo botão, apaga tudo, restaura o arquivo e compara
    entrar_demo(ed)
    tela(ed, "ajustes")
    ed.js("window.__blobs = {}; const orig = URL.createObjectURL;"
          "URL.createObjectURL = b => { const u = orig.call(URL, b); window.__blobs[u] = b; return u; };"
          "HTMLAnchorElement.prototype.click = function(){ window.__baixado = {nome: this.download, url: this.href}; };")
    antes = estado(ed)
    ed.js("document.getElementById('btn-exportar').click()", espera=0.3)
    baixado = ed.js("(async () => ({nome: window.__baixado.nome, texto: await window.__blobs[window.__baixado.url].text()}))()")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        f.write(baixado["texto"])
        caminho_backup = f.name
    abrir_limpo(ed)
    ed.js("document.getElementById('pa-pular').click()", espera=0.4)
    tela(ed, "ajustes")
    arquivo(ed, "#backup-arquivo", caminho_backup)
    depois = estado(ed)
    os.unlink(caminho_backup)
    checa("backup: exportar e restaurar devolve exatamente os mesmos dados",
          baixado["nome"].startswith("financas-backup-") and json.loads(baixado["texto"]) == antes == depois,
          f"{baixado['nome']}, {len(depois['tx'])} lançamentos de {len(antes['tx'])}")

    # 16. persistência: lança, recarrega e continua lá
    tela(ed, "hoje")
    digitar(ed, "12")
    tocar(ed, '#cats [data-cat="cafe"]', 0.3)
    id16 = estado(ed)["tx"][-1]["id"]
    topo16 = topo(ed)
    ed.js("location.reload()")
    ed.esperar(2.0)
    s16 = estado(ed)
    checa("depois de recarregar, o lançamento e o número do topo continuam",
          s16["tx"][-1]["id"] == id16 and topo(ed) == topo16 == conta_hoje(s16, hoje)[2], f"topo {topo16} -> {topo(ed)}")

    # 17. tema escuro pelos Ajustes, e ele fica depois de recarregar (sem ?tema na URL)
    ed.ir(URL + "#ajustes", espera=1.5)
    ed.js("document.querySelector('[data-tema=\"escuro\"]').click()", espera=0.3)
    fundo = ed.js("getComputedStyle(document.body).backgroundColor")
    ed.js("location.reload()")
    ed.esperar(1.8)
    r17 = ed.js("({tema: document.documentElement.dataset.theme, fundo: getComputedStyle(document.querySelector('.app')).backgroundColor,"
                " salvo: JSON.parse(localStorage.getItem('OF_v1')).config.tema})")
    rgb = [int(x) for x in r17["fundo"].replace("rgb(", "").replace(")", "").split(",")[:3]]
    checa("tema escuro: troca nos Ajustes, o fundo fica escuro e continua depois de recarregar",
          r17["tema"] == "dark" and r17["salvo"] == "escuro" and max(rgb) < 60, f"{r17}, body {fundo}")
    for nome in TELAS:
        tela(ed, nome)
        textos.append(ed.js("document.body.innerText"))
    ed.js("document.querySelector('[data-tema=\"claro\"]').click()", espera=0.2)

    # 18. celular 390 x 844: nada vaza, alvos de toque, teclado e barra sem rolar
    entrar_demo(ed)
    problemas = []
    def mede(onde):
        m = ed.js("({w: innerWidth, sw: document.documentElement.scrollWidth, fora: [...document.querySelectorAll('body *')]"
                  ".filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.right > innerWidth + 1 && !e.closest('.cats, .chips'); })"
                  ".slice(0, 3).map(e => e.tagName + '.' + e.className),"
                  " pequenos: [...document.querySelectorAll('button, a, input, select')].filter(e => { const r = e.getBoundingClientRect();"
                  " return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden' && (r.height < 44 || r.width < 44); })"
                  ".slice(0, 4).map(e => (e.id || e.textContent.trim().slice(0, 12) || e.tagName) + ' ' + Math.round(e.getBoundingClientRect().width) + 'x' + Math.round(e.getBoundingClientRect().height)),"
                  " texto: document.body.innerText})")
        textos.append(m["texto"])
        if m["w"] != 390 or m["sw"] != 390 or m["fora"] or m["pequenos"]:
            problemas.append(f"{onde}: innerWidth {m['w']}, scrollWidth {m['sw']}, fora {m['fora']}, pequenos {m['pequenos']}")
    for nome in TELAS:
        tela(ed, nome)
        mede(nome)
        if nome == "calc":
            ed.js("document.getElementById('calc-aba-parcelas').click()", espera=0.2)
            mede("parcelas")
            ed.js("document.getElementById('calc-aba-comum').click()", espera=0.2)
    tela(ed, "hoje")
    ed.js("document.querySelector('#ultimos .item').click()", espera=0.4)
    mede("folha de edição")
    ed.js("document.getElementById('folha').close()")
    tela(ed, "ajustes")
    ed.js("document.getElementById('btn-importar').click()", espera=0.4)
    mede("folha de importar")
    ed.js("document.getElementById('folha').close(); location.hash = '#hoje'", espera=0.4)
    ed.js("aplicarLeitura({valor: 8745, data: null, loja: 'Padaria Doce Lar'})", espera=0.4)
    mede("faixa da notinha")
    ed.js("limparDIG(); renderHoje(); abrirPrimeiro()", espera=0.3)
    for passo in (1, 2, 3, 4):
        mede(f"primeiro acesso, passo {passo}")
        ed.js("seguir()", espera=0.3)
    ed.js("limparDIG(); renderHoje()")
    ed.js("document.getElementById('folha').close()")
    checa("390 px com 5 abas: innerWidth 390, scrollWidth 390, nada vaza e todo alvo de toque tem 44 px (telas, folhas e notinha)",
          not problemas, "; ".join(problemas)[:500])
    tela(ed, "hoje")
    ed.js("window.scrollTo(0, 0)", espera=0.2)
    v = ed.js("(() => { const r = id => document.getElementById(id).getBoundingClientRect(), t = r('teclado'), n = r('nav'), c = r('cats'),"
              " vi = r('visor'), f = r('btn-notinha');"
              " return {h: innerHeight, sy: scrollY, topo: r('hoje-valor').top, cats: c.top, catsBase: c.bottom, tecTopo: t.top, tecBase: t.bottom,"
              " navTopo: n.top, navBase: n.bottom, visorBase: vi.bottom, fotoBase: f.bottom, fotoAlt: f.height, fotoLarg: f.width,"
              " pergunta: document.getElementById('visor').textContent, foto: document.getElementById('btn-notinha').textContent}; })()")
    checa("390 x 844 na tela Hoje, sem rolar: visor com a pergunta, botão 'Fotografar nota', categorias, teclado e barra",
          v["h"] == 844 and v["sy"] == 0 and v["topo"] >= 0 and v["pergunta"] == "Quanto você gastou?" and v["foto"] == "Fotografar nota"
          and v["fotoAlt"] >= 44 and v["fotoLarg"] >= 120 and max(v["visorBase"], v["fotoBase"], v["catsBase"]) <= v["navTopo"]
          and v["tecTopo"] > v["cats"] and v["tecBase"] <= v["navTopo"] and v["navBase"] <= 844,
          str({k: (round(x) if isinstance(x, (int, float)) else x) for k, x in v.items()}))

    # 19. nenhum travessão, "undefined" ou "NaN" em texto visível, no app e no README
    fonte = (RAIZ / "index.html").read_text(encoding="utf-8") + (RAIZ / "README.md").read_text(encoding="utf-8")
    ruins = sorted({r for t in textos for r in (TRAVESSAO, "undefined", "NaN") if r in t})
    checa("nenhum travessão (nem 'undefined' ou 'NaN') no texto da tela, no index.html e no README",
          not ruins and TRAVESSAO not in fonte, f"tela: {ruins}, arquivo: {TRAVESSAO in fonte}, {len(textos)} telas lidas")

    # 20. dados do app antigo (formato 3) abrem migrados
    velho = {"schema_v": 3, "config": {"salarioBruto": 450000, "regime": "liquido", "tema": "claro"},
             "categorias": [{"id": "mercado", "nome": "Mercado", "tipo": "d", "fixa": False, "orc": 80000},
                            {"id": "aluguel", "nome": "Aluguel", "tipo": "d", "fixa": True},
                            {"id": "salario", "nome": "Salário", "tipo": "r", "fixa": False}],
             "recorrentes": [{"id": "r1", "nome": "Aluguel", "valor": 120000, "tipo": "d", "cat": "aluguel", "ativo": True},
                             {"id": "r2", "nome": "Pausada", "valor": 5000, "tipo": "d", "cat": "aluguel", "ativo": False}],
             "tx": [{"id": "a", "d": f"{ym}-01", "desc": "Aluguel", "v": -120000, "cat": "aluguel"},
                    {"id": "b", "d": f"{ym}-01", "desc": "Feira", "v": -5000, "cat": "mercado"},
                    {"id": "c", "d": f"{ym}-01", "desc": "Salário", "v": 450000, "cat": "salario"}]}
    ed.js(f"localStorage.clear(); localStorage.setItem('OF_v1', {json.dumps(json.dumps(velho))}); location.hash = '#hoje'; location.reload()")
    ed.esperar(2.0)
    s20 = estado(ed)
    cats20 = {t["id"]: t["cat"] for t in s20["tx"]}
    lim = next(c.get("limite") for c in s20["cats"] if c["id"] == "mercado")
    checa("dados do app antigo abrem: renda, contas fixas, categorias e limite migrados (cópia antiga guardada)",
          s20["schema_v"] == 4 and s20["config"]["renda"] == 450000 and [f["v"] for f in s20["fixas"]] == [120000]
          and cats20 == {"a": "fixas", "b": "mercado", "c": "salario"} and lim == 80000
          and ed.js("!!localStorage.getItem('OF_v1_formato3')") and not ed.js("document.getElementById('folha').open")
          and ed.js("document.getElementById('primeiro').hidden"),
          f"renda {s20['config']['renda']}, fixas {s20['fixas']}, cats {cats20}, limite {lim}")

    # contraste AA (4,5:1) dos pares de texto e fundo principais, medido nas variáveis do tema
    PARES = [("tx", "fundo"), ("tx", "sup"), ("tx", "tecla"), ("tx2", "fundo"), ("tx2", "sup"), ("tx2", "tecla"), ("tx3", "sup"),
             ("tx3", "tecla"), ("acc", "fundo"), ("acc", "sup"), ("sobre-acc", "acc"), ("entrada-tx", "fundo"),
             ("entrada-tx", "sup"), ("alerta-tx", "fundo"), ("alerta-tx", "sup"), ("toast-tx", "toast-fundo"), ("toast-acc", "toast-fundo")]
    ruins = []
    for tema_css in ("light", "dark"):
        ed.js(f"document.documentElement.dataset.theme = '{tema_css}'")
        nomes = sorted({x for par in PARES for x in par})
        cores = ed.js("(() => { const c = getComputedStyle(document.documentElement); return Object.fromEntries("
                      + json.dumps(nomes) + ".map(n => [n, c.getPropertyValue('--' + n).trim()])); })()")
        for frente, fundo in PARES:
            base = cor(cores["fundo"])
            r = contraste(cor(cores[frente], base), cor(cores[fundo], base))
            if r < 4.5:
                ruins.append(f"{tema_css} {frente}/{fundo} {r:.2f}")
    ed.js("document.documentElement.dataset.theme = 'light'")
    checa(f"contraste AA: os {len(PARES)} pares de texto e fundo passam de 4,5:1 no claro e no escuro", not ruins, "; ".join(ruins))

    # aparência (rodada 3): sem emoji, uma família de fonte, nenhum <select>, rosé só onde é permitido
    EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u231A\u231B\u23E9-\u23FA]")
    com_emoji = sorted({m for t in textos for m in EMOJI.findall(t)})
    checa("nenhum emoji no texto da interface (todas as telas, folhas e a faixa da notinha)", not com_emoji,
          f"{com_emoji}, {len(textos)} telas lidas")
    entrar_demo(ed)
    familias, fora_do_numero, selects = set(), [], []
    for nome in TELAS:
        tela(ed, nome)
        r = ed.js("(() => { const out = {fam: [], serif: [], sel: 0};"
                  " document.querySelectorAll('body *').forEach(e => { const r = e.getBoundingClientRect();"
                  "  if(!r.width || !r.height) return;"
                  "  if(e.tagName === 'SELECT') out.sel++;"
                  "  if(![...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) return;"
                  "  const f = getComputedStyle(e).fontFamily.split(',')[0].replace(/[\"']/g, '').trim();"
                  "  if(/fraunces/i.test(f)) out.serif.push(e.id || e.className); else out.fam.push(f); });"
                  " return out; })()")
        familias |= set(r["fam"])
        fora_do_numero += [x for x in r["serif"] if x not in ("hoje-valor", "logo-nome")]
        if r["sel"]:
            selects.append(f"{nome}: {r['sel']}")
    checa("uma família de fonte só na interface (a serifada só no número do 'Hoje dá para gastar' e no logotipo)",
          len(familias) == 1 and not fora_do_numero, f"famílias {sorted(familias)}, serifada fora do número: {fora_do_numero[:3]}")
    checa("nenhum <select> visível (nas 5 telas e no importador depois de ler o arquivo)", not selects and selects_import == 0,
          f"{selects}, importador {selects_import}")
    tela(ed, "hoje")
    rose = ed.js("(() => { const t = document.createElement('i'); t.style.background = 'var(--acc)'; document.body.appendChild(t);"
                 " const cor = getComputedStyle(t).backgroundColor; t.remove();"
                 " return [...document.querySelectorAll('body *')].filter(e => { const r = e.getBoundingClientRect();"
                 "  return r.width > 0 && r.height > 0 && getComputedStyle(e).backgroundColor === cor; })"
                 "  .map(e => e.id || e.className || e.tagName); })()")
    checa("na tela Hoje, no máximo 4 elementos com fundo no acento argila (botão principal, categoria escolhida)", len(rose) <= 4, f"{len(rose)}: {rose}")

    # nenhum rosa: fundo e texto de todo elemento visível, nas 5 telas, claro e escuro
    rosas = []
    for tema_css in ("light", "dark"):
        ed.js(f"document.documentElement.dataset.theme = '{tema_css}'")
        for nome in TELAS:
            tela(ed, nome)
            cores = ed.js("(() => { const out = new Set(); document.querySelectorAll('body *').forEach(e => { const r = e.getBoundingClientRect();"
                          " if(!r.width || !r.height) return; const c = getComputedStyle(e);"
                          " out.add(c.backgroundColor); if([...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) out.add(c.color); });"
                          " return [...out]; })()")
            for c in cores:
                if eh_rosa(c):
                    rosas.append(f"{tema_css}/{nome}: {c}")
    ed.js("document.documentElement.dataset.theme = 'light'")
    tela(ed, "ajustes")
    logo_aj = ed.js("(document.querySelector('#tela-ajustes .logo-nome') || {}).textContent")
    checa("nenhum rosa ou magenta (matiz 300 a 360 ou 0 a 15, saturação acima de 25%) em fundo ou texto; logotipo no topo dos Ajustes",
          not rosas and logo_aj == "Vintém", "; ".join(sorted(set(rosas)))[:300] + f" logo {logo_aj!r}")

    checa("nenhum erro de JavaScript na bateria inteira", not ed.erros(), "; ".join(ed.erros())[:300])

    # fotos para o README e a miniatura do portfólio (só com --fotos)
    if "--fotos" in sys.argv:
        with Edge(390, 844, escala=2) as cel:
            for tema, saida in (("claro", "celular-hoje.png"), ("escuro", "celular-escuro.png")):
                entrar_demo(cel, tema)
                cel.esperar(0.8)
                cel.foto(str(DOCS / saida))
            entrar_demo(cel, "claro")
            tela(cel, "mes")
            cel.foto(str(DOCS / "celular-mes.png"))
            tela(cel, "hist")
            cel.foto(str(DOCS / "celular-historico.png"))
            tela(cel, "hoje")
            # a faixa "Confira os dados da nota" com o que a leitura devolveria de uma notinha de padaria
            cel.js("aplicarLeitura({valor: 8745, data: null, loja: 'Padaria Doce Lar'})", espera=0.6)
            cel.foto(str(DOCS / "celular-notinha.png"))
            cel.js("limparDIG(); renderHoje()")
            tela(cel, "calc")
            cel.js("document.getElementById('calc-aba-parcelas').click()", espera=0.3)
            cel.foto(str(DOCS / "calculadoras.png"))
        with Edge(390, 844, escala=2) as cel:
            abrir_limpo(cel, "claro")
            cel.foto(str(DOCS / "primeiro-acesso.png"))
            entrar_demo(cel, "claro")
            tela(cel, "calc")
            cel.js("document.getElementById('calc-aba-parcelas').click()", espera=0.3)
            cel.js("(() => { const v = {preco: '1.800,00', n: '6', juros: '0', desc: '0', rend: '0'};"
                   " Object.keys(v).forEach(k => { const i = document.getElementById('parc-' + k); i.value = v[k]; i.dispatchEvent(new Event('input')); }); })()", espera=0.2)
            cel.js("document.getElementById('parc-ver').click()", espera=0.3)
            cel.js("document.getElementById('parc-ver').scrollIntoView({block: 'start'})", espera=0.3)
            cel.foto(str(DOCS / "parcelas.png"))
        with Edge(1440, 900) as pc:
            entrar_demo(pc, "claro")
            pc.esperar(0.8)
            pc.foto(str(DOCS / "visao-geral.png"))
        print("fotos gravadas em", DOCS)

print()
print("RESULTADO:", "TUDO OK" if not falhas else f"{len(falhas)} FALHA(S): " + "; ".join(falhas))
sys.exit(1 if falhas else 0)
