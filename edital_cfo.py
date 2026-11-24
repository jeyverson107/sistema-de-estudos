"""Itens do conteúdo programático do edital CBMPE nº 002/2026 (Anexo II, cargo 2º Tenente BM – QOC)
e a ligação de cada item com os blocos do cronograma "CFO CBMPE 2027".

Serve para medir o AVANÇO NO EDITAL: quanto de cada matéria (e do total) já foi estudado.
Os textos dos itens resumem o Anexo II; a numeração segue o edital quando ele numera.
"""
import re

LEG, CF, ADM, DPM = "Legislação dos Militares de PE", "Direito Constitucional", "Direito Administrativo", "Direito Penal Militar"
PORT, ESP, INFO, EST = "Língua Portuguesa", "Língua Estrangeira", "Informática", "Estatística"
MAT, FIS, QUI, BIO = "Matemática", "Física", "Química", "Biologia"

# Questões de cada matéria na prova objetiva (Tabela 10.2 do edital) – peso no avanço global
QUESTOES_PROVA = {PORT: 5, ESP: 5, INFO: 5, EST: 5, MAT: 5, FIS: 5, QUI: 5, BIO: 5,
                  CF: 8, ADM: 7, LEG: 10, DPM: 5}

# código do item -> (matéria, texto do item no edital)
ITENS = {}
def _itens(materia, prefixo, textos):
    for i, t in enumerate(textos, 1):
        ITENS[f"{prefixo}{i}"] = (materia, t)

_itens(PORT, "POR", [
    "1. Compreensão e interpretação de textos", "2. Tipologias e gêneros textuais", "3. Figuras de linguagem",
    "4. Relações semânticas entre orações, períodos e parágrafos", "5. Ortografia oficial", "6. Acentuação gráfica",
    "7. Emprego das classes de palavras", "8. Emprego do sinal indicativo de crase",
    "9. Sintaxe da oração e do período (coordenação e subordinação)", "10. Funções do \"que\" e do \"se\"",
    "11. Mecanismos de coesão textual", "12. Emprego e funções dos sinais de pontuação", "13. Concordância nominal e verbal",
    "14. Regência nominal e verbal", "15. Colocação pronominal", "16. Processos de formação de palavras",
    "17. Significação das palavras", "18. Variação linguística"])
_itens(ESP, "ESP", [
    "1. Leitura e compreensão de textos; determinantes do nome", "2. Substantivos: gênero, número e grau",
    "3. Adjetivos: gênero, número e grau", "4. Pronomes", "5. Verbos (regulares, irregulares, impessoais, pronominais, perífrases)",
    "6. Advérbios e locuções adverbiais", "7. Preposições", "8. Conjunções coordenativas e subordinativas", "9. Acentuação",
    "10. Sinônimos e antônimos",
    "11. Divergências português × espanhol (heterográficos, heteroprosódicos, heterogenéricos, heterossemânticos)"])
_itens(INFO, "INF", [
    "Conceitos de internet e intranet", "Navegadores, serviços e computação em nuvem",
    "Segurança da informação (ameaças, malwares, phishing, criptografia, autenticação)",
    "Armazenamento e backup (tipos e restauração)",
    "Organização de arquivos e pastas; componentes do computador e periféricos", "Windows 11 (Painel de Controle, Prompt de Comando)",
    "Office 2019 e LibreOffice 7 (Word/Writer, Excel/Calc, PowerPoint/Impress)"])
_itens(EST, "EST", [
    "1. População, censo, amostra aleatória e normas de apresentação de dados",
    "2. Probabilidade: definições clássica, geométrica e axiomática",
    "3. Variáveis aleatórias e distribuições de probabilidade",
    "4. Medidas de centralidade, posição e dispersão; histograma e boxplot",
    "5. Testes de hipóteses: t, F e ANOVA", "6. Regressão linear"])
_itens(MAT, "MAT", [
    "1. Conhecimentos numéricos (conjuntos, razão e proporção, porcentagem, juros, sequências, contagem)",
    "2. Conhecimentos geométricos (figuras, medidas, semelhança, Tales, relações métricas, trigonometria do ângulo agudo)",
    "3. Estatística e probabilidade (dados, média/moda/mediana, desvios e variância, probabilidade)",
    "4. Conhecimentos algébricos (funções, equações e inequações, ciclo trigonométrico)",
    "5. Conhecimentos algébrico-geométricos (plano cartesiano, retas, circunferência, sistemas)"])
_itens(FIS, "FIS", [
    "1. Fundamentos: grandezas, notação científica, SI e vetores", "2. Movimento, equilíbrio e leis físicas (inclui hidrostática)",
    "3. Energia, trabalho e potência", "4. Mecânica e funcionamento do universo (gravitação, Kepler, marés)",
    "5. Fenômenos elétricos e magnéticos", "6. Oscilações, ondas, óptica e radiação", "7. Calor e fenômenos térmicos"])
_itens(QUI, "QUI", [
    "1.1 Substâncias, misturas, pureza e separação", "1.2 Átomos e moléculas", "1.3 Classificação periódica",
    "1.4 Ligações químicas", "1.5 Fórmulas, Lewis, nomenclatura e Nox", "1.6 Óxidos, ácidos, bases e sais",
    "1.7 Estados da matéria e gases", "1.8 Soluções", "1.9 Radioatividade e estrutura nuclear",
    "2.1 Reações e estequiometria", "2.2 Termoquímica", "2.3 Cinética química", "2.4 Equilíbrio químico",
    "2.5 Solubilidade, equilíbrio iônico, pH e tampão", "2.6 Oxirredução, pilhas e eletrólise",
    "3.1 Química orgânica: características e funções", "3.2 Nomenclatura e isomeria", "3.3 Ligação química em compostos orgânicos",
    "3.4 Acidez e basicidade orgânicas", "3.5 Reações orgânicas e solventes",
    "4.1 Petróleo e combustíveis", "4.3 Polímeros", "4.6 Siderurgia",
    "5. Produtos químicos perigosos e FDS", "5. Aspectos químicos do fogo e da combustão", "6. Água: propriedades e tratamento"])
_itens(BIO, "BIO", [
    "1. Moléculas, células e tecidos (inclui genética e biotecnologia)", "2. Identidade dos seres vivos (evolução, classificação, fisiologia humana)",
    "3. Ecologia e ciências ambientais", "4. Qualidade de vida das populações humanas"])
_itens(CF, "CF", [
    "1. Constituição: conceito, classificação, histórico e elementos", "2. Estrutura da Constituição",
    "3. Poder constituinte; mutação, recepção, repristinação", "4. Eficácia e aplicabilidade das normas constitucionais",
    "5. Controle de constitucionalidade (ADI, ADO, ADC, ADPF, representação interventiva)",
    "6. Direitos e garantias fundamentais e remédios constitucionais",
    "7. Organização do Estado (federação, competências, Administração Pública e servidores)",
    "8. Organização dos Poderes", "9. Funções essenciais à Justiça", "10. Defesa do Estado e das instituições democráticas",
    "11. Ordem social", "12. Constituição do Estado de Pernambuco", "13. Súmulas e jurisprudência dos Tribunais Superiores",
    "14. ECA (Lei 8.069/1990)", "15. Estatuto da Juventude (Lei 12.852/2013)", "16. Lei Maria da Penha (Lei 11.340/2006)"])
_itens(ADM, "ADM", [
    "1. Estado, governo e administração pública: conceitos, elementos, poderes, organização, natureza, fins e princípios",
    "2. Direito Administrativo: conceito, fontes e princípios",
    "3. Organização administrativa: centralização, descentralização, concentração, desconcentração; direta e indireta",
    "4. Agentes públicos: espécies, deveres e prerrogativas, cargo/emprego/função, provimento, vacância, regime disciplinar e responsabilidades",
    "5. Poderes administrativos e uso e abuso do poder",
    "6. Ato administrativo: requisitos, atributos, extinção, convalidação, classificação e espécies",
    "7. Serviços públicos (concessão, permissão e autorização)",
    "8. Controle e responsabilização da administração; responsabilidade civil do Estado"])
_itens(LEG, "LEG", [
    "Estatuto (Lei 6.783/1974): hierarquia e disciplina", "Estatuto: cargo e função", "Estatuto: obrigações e deveres",
    "Estatuto: direitos, prerrogativas e proteção social", "Estatuto: situações especiais",
    "Estatuto: desligamento ou exclusão do serviço ativo", "Estatuto: tempo de serviço",
    "Código Disciplinar (Lei 11.817/2000): regime disciplinar e transgressões", "Código Disciplinar: penas e medidas administrativas",
    "Código Disciplinar: recursos e comissões recursais", "Código Disciplinar: cancelamento de penas e recompensas",
    "Código Disciplinar: transgressões em espécie", "Decreto 50.014/2020 (regulamenta a Lei 11.817)",
    "Lei 15.187/2013: generalidades e organização básica do CBMPE", "Lei 15.187/2013: atribuições funcionais e orgânicas; pessoal",
    "Lei 14.751/2023 (Lei Orgânica Nacional das PMs e CBMs)"])
_itens(DPM, "DPM", [
    "1. Aplicação da lei penal militar", "2. Do crime", "3. Imputabilidade penal", "4. Concurso de agentes", "5. Das penas",
    "6. Das medidas de segurança", "7. Da ação penal", "8. Extinção da punibilidade", "9. Crimes militares em tempo de paz",
    "10. Crimes militares em tempo de guerra", "11. Súmulas e jurisprudência dos Tribunais Superiores"])

# (matéria do bloco, assunto do bloco) -> itens do edital que ele cobre.
# Só blocos de CONTEÚDO contam; blocos só de questões, revisão, lei seca e simulado não entram.
BLOCOS = {
    (PORT, "Interpretação, tipologia e gêneros textuais"): ["POR1", "POR2"],
    (PORT, "Classes de palavras I"): ["POR7"], (PORT, "Classes de palavras II"): ["POR7"],
    (PORT, "Funções do QUE e do SE"): ["POR10"], (PORT, "Termos da oração"): ["POR9"],
    (PORT, "Coordenação e subordinação"): ["POR9"], (PORT, "Pontuação"): ["POR12"], (PORT, "Concordância"): ["POR13"],
    (PORT, "Regência e crase"): ["POR14", "POR8"], (PORT, "Colocação pronominal"): ["POR15"],
    (PORT, "Ortografia e acentuação"): ["POR5", "POR6"], (PORT, "Coesão e relações semânticas"): ["POR11", "POR4"],
    (PORT, "Figuras de linguagem, significação e formação de palavras"): ["POR3", "POR17", "POR16"],
    (PORT, "Variação linguística e interpretação"): ["POR18", "POR1"],

    (ESP, "Espanhol: interpretação de textos e determinantes"): ["ESP1"],
    (ESP, "Espanhol: substantivos, adjetivos e pronomes"): ["ESP2", "ESP3", "ESP4"],
    (ESP, "Espanhol: verbos, advérbios, preposições e conjunções"): ["ESP5", "ESP6", "ESP7", "ESP8"],
    (ESP, "Espanhol: acentuação, heterossemânticos e questões"): ["ESP9", "ESP10", "ESP11"],

    (INFO, "segurança da informação"): ["INF3"],
    (INFO, "Windows 11, hardware e backup"): ["INF4", "INF5", "INF6"],
    (INFO, "Excel e Calc"): ["INF7"],
    (INFO, "internet, nuvem e editores (Word/Writer e PowerPoint/Impress)"): ["INF1", "INF2", "INF7"],

    (EST, "conceitos e apresentação de dados"): ["EST1", "MAT3"],
    (EST, "média, moda, mediana"): ["EST4", "MAT3"],
    (EST, "variância, desvio, CV, boxplot"): ["EST4", "MAT3"],
    (EST, "probabilidade"): ["EST2"], (EST, "variáveis aleatórias e distribuições"): ["EST3"],
    (EST, "testes t, F e ANOVA (interpretação)"): ["EST5"], (EST, "regressão linear"): ["EST6"],

    (MAT, "conjuntos numéricos, razão, proporção e porcentagem"): ["MAT1"],
    (MAT, "juros, PA e PG"): ["MAT1"],
    (MAT, "geometria plana e espacial"): ["MAT2"],
    (MAT, "funções (inclusive exponencial e logarítmica), equações e inequações"): ["MAT4"],
    (MAT, "contagem e probabilidade"): ["MAT1", "MAT3"],
    (MAT, "trigonometria, geometria analítica e sistemas"): ["MAT2", "MAT4", "MAT5"],

    (FIS, "grandezas, vetores e cinemática (MU e MUV)"): ["FIS1", "FIS2"],
    (FIS, "dinâmica (Leis de Newton), quantidade de movimento e equilíbrio"): ["FIS2"],
    (FIS, "hidrostática e empuxo"): ["FIS2"],
    (FIS, "trabalho, energia, potência e gravitação"): ["FIS3", "FIS4"],
    (FIS, "termologia e gases"): ["FIS7"],
    (FIS, "eletrostática, eletrodinâmica e magnetismo"): ["FIS5"],
    (FIS, "óptica e ondas"): ["FIS6"],

    (QUI, "fogo, combustão, petróleo e combustíveis"): ["QUI25", "QUI21"],
    (QUI, "misturas, átomo e tabela periódica"): ["QUI1", "QUI2", "QUI3"],
    (QUI, "ligações e funções inorgânicas"): ["QUI4", "QUI5", "QUI6"],
    (QUI, "gases, soluções, estequiometria e água"): ["QUI7", "QUI8", "QUI10", "QUI26"],
    (QUI, "produtos perigosos, oxirredução e siderurgia"): ["QUI24", "QUI15", "QUI23"],
    (QUI, "termoquímica, cinética, equilíbrio e pH"): ["QUI11", "QUI12", "QUI13", "QUI14"],
    (QUI, "orgânica I: carbono, cadeias, funções e nomenclatura"): ["QUI16", "QUI17", "QUI18"],
    (QUI, "orgânica II: isomeria, acidez, reações, polímeros e radioatividade"): ["QUI9", "QUI17", "QUI19", "QUI20", "QUI22"],

    (BIO, "citologia e metabolismo"): ["BIO1"], (BIO, "genética e biotecnologia"): ["BIO1"],
    (BIO, "evolução, classificação, embriologia e fisiologia humana"): ["BIO2"],
    (BIO, "ecologia"): ["BIO3"], (BIO, "biomas e problemas ambientais"): ["BIO3"],
    (BIO, "saúde, doenças e primeiros socorros"): ["BIO4"],

    (CF, "Constituição: conceito e classificação"): ["CF1", "CF2"],
    (CF, "Poder constituinte"): ["CF3"],
    (CF, "Eficácia e aplicabilidade das normas constitucionais"): ["CF4"],
    (CF, "Eficácia das normas; princípios fundamentais"): ["CF4"],  # nome antigo do mesmo bloco
    (CF, "Direitos individuais (art. 5º) – parte 1"): ["CF6"], (CF, "Art. 5º – parte 2 e remédios constitucionais"): ["CF6"],
    (CF, "Direitos sociais e nacionalidade"): ["CF6"], (CF, "Direitos políticos e partidos"): ["CF6"],
    (CF, "Organização do Estado: federação e União"): ["CF7"], (CF, "Estados, Municípios e repartição de competências"): ["CF7"],
    (CF, "Administração Pública (arts. 37 a 41)"): ["CF7"], (CF, "Militares dos Estados (art. 42)"): ["CF7"],
    (CF, "Poder Legislativo"): ["CF8"], (CF, "Poder Executivo"): ["CF8"], (CF, "Poder Judiciário"): ["CF8"],
    (CF, "Funções essenciais à Justiça"): ["CF9"],
    (CF, "Estado de defesa e estado de sítio"): ["CF10"], (CF, "Segurança pública (art. 144) e Forças Armadas"): ["CF10"],
    (CF, "Ordem social"): ["CF11"],
    (CF, "Controle de constitucionalidade: difuso e concentrado"): ["CF5"], (CF, "ADI, ADC, ADO e ADPF"): ["CF5"],
    (CF, "Constituição do Estado de Pernambuco"): ["CF12"],
    (CF, "ECA (Lei 8.069/1990)"): ["CF14"], (CF, "Lei Maria da Penha e Estatuto da Juventude"): ["CF15", "CF16"],
    (CF, "Súmulas, jurisprudência e questões AOCP"): ["CF13"],

    (ADM, "Estado, governo e administração; fontes"): ["ADM1", "ADM2"],
    (ADM, "Princípios da administração"): ["ADM1", "ADM2"],
    (ADM, "Centralização, descentralização e desconcentração"): ["ADM3"], (ADM, "Administração indireta"): ["ADM3"],
    (ADM, "Agentes públicos: espécies, cargo, emprego, função"): ["ADM4"],
    (ADM, "Agentes: provimento, vacância e acumulação"): ["ADM4"],
    (ADM, "Agentes: regime disciplinar e responsabilidades"): ["ADM4"],
    (ADM, "Poderes: vinculado, discricionário, hierárquico, disciplinar, regulamentar"): ["ADM5"],
    (ADM, "Poder de polícia e abuso de poder"): ["ADM5"],
    (ADM, "Ato administrativo: requisitos e atributos"): ["ADM6"], (ADM, "Ato: classificação e espécies"): ["ADM6"],
    (ADM, "Ato: anulação, revogação e convalidação"): ["ADM6"],
    (ADM, "Serviços públicos"): ["ADM7"],
    (ADM, "Controle da administração"): ["ADM8"], (ADM, "Responsabilidade civil do Estado"): ["ADM8"],

    (LEG, "Estatuto (Lei 6.783): hierarquia e disciplina"): ["LEG1"],
    (LEG, "Estatuto: cargo e função, obrigações e deveres"): ["LEG2", "LEG3"],
    (LEG, "Estatuto: direitos, prerrogativas, férias e licenças"): ["LEG4"],
    (LEG, "Estatuto: situações especiais e proteção social"): ["LEG5", "LEG4"],
    (LEG, "Estatuto: desligamento, exclusão, tempo de serviço"): ["LEG6", "LEG7"],
    (LEG, "Cód. Disciplinar (Lei 11.817): regime disciplinar e transgressões"): ["LEG8"],
    (LEG, "Cód. Disciplinar: penas e medidas administrativas"): ["LEG9"],
    (LEG, "Cód. Disciplinar: processo, recursos, comissões recursais"): ["LEG10"],
    (LEG, "Cód. Disciplinar: cancelamento, recompensas, transgressões em espécie"): ["LEG11", "LEG12"],
    (LEG, "Decreto 50.014/2020"): ["LEG13"],
    (LEG, "Lei 15.187/2013 (CBMPE): generalidades e organização"): ["LEG14"],
    (LEG, "Lei 15.187/2013: atribuições e pessoal"): ["LEG15"],
    (LEG, "Lei 14.751/2023: princípios, competências, quadros"): ["LEG16"],
    (LEG, "Lei 14.751/2023: direitos, garantias, ingresso"): ["LEG16"],

    (DPM, "Aplicação da lei penal militar"): ["DPM1"],
    (DPM, "Crime militar: art. 9º do CPM e Lei 13.491/2017"): ["DPM2"],
    (DPM, "Crime militar próprio e impróprio + questões"): ["DPM2"],
    (DPM, "Tempo e lugar do crime; dolo e culpa"): ["DPM2"],
    (DPM, "Excludentes de ilicitude e culpabilidade"): ["DPM2"],
    (DPM, "Imputabilidade penal"): ["DPM3"], (DPM, "Concurso de agentes"): ["DPM4"],
    (DPM, "Penas principais"): ["DPM5"], (DPM, "Penas acessórias"): ["DPM5"],
    (DPM, "Aplicação da pena e suspensão condicional"): ["DPM5"],
    (DPM, "Medidas de segurança"): ["DPM6"], (DPM, "Ação penal militar"): ["DPM7"],
    (DPM, "Extinção da punibilidade"): ["DPM8"], (DPM, "Prescrição"): ["DPM8"],
    (DPM, "Crimes contra a autoridade e a disciplina"): ["DPM9"],
    (DPM, "Crimes contra o serviço e o dever militar"): ["DPM9"], (DPM, "Demais crimes contra o serviço militar"): ["DPM9"],
    (DPM, "Crimes contra a administração militar"): ["DPM9"], (DPM, "Crimes contra a pessoa e o patrimônio"): ["DPM9"],
    (DPM, "Crimes em tempo de guerra (visão geral)"): ["DPM10"],
    (DPM, "Súmulas do STF, STJ e STM"): ["DPM11"],
}

# Títulos de blocos trocados em 21/11/2026 (matéria, antigo, novo)
RENOMEAR_2026_11_21 = [
    (CF, "Eficácia das normas; princípios fundamentais", "Eficácia e aplicabilidade das normas constitucionais"),
]

# Blocos de Química reorganizados em 24/11/2026 (matéria, antigo, novo)
RENOMEAR_2026_11_24 = [
    (QUI, "fogo e combustão", "fogo, combustão, petróleo e combustíveis"),
    (QUI, "radioatividade, orgânica e química aplicada", "orgânica I: carbono, cadeias, funções e nomenclatura"),
    (QUI, "questões AOCP", "orgânica II: isomeria, acidez, reações, polímeros e radioatividade"),
]


def _assunto(nome):
    """'S01 Seg 12/10 · Continuação: X (parte 2)' -> ('X', é_lei_seca)."""
    t = str(nome).split(" · ", 1)[-1].strip()
    lei_seca = t.lower().startswith("lei seca:")
    t = re.sub(r"\s*\((parte \d+|questões)\)\s*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^(Lei seca|Continuação):\s*", "", t, flags=re.IGNORECASE)
    return t.strip(), lei_seca


def itens_do_bloco(materia, nome_topico):
    """Textos dos itens do edital que o bloco cobre (lista vazia se não for bloco de conteúdo)."""
    assunto, _ = _assunto(nome_topico)
    return [ITENS[c][1] if ITENS[c][0] == materia else f"{ITENS[c][0]}: {ITENS[c][1]}"
            for c in BLOCOS.get((materia, assunto), [])]


CREDITO = {"Concluído": 1.0, "Parcial": 0.5}


def calcular_avanco(blocos, idx_hoje=None):
    """blocos: lista de dicts com 'materia', 'nome', 'status' e (opcional) 'idx' = posição do dia no cronograma.
    Cada item do edital vale a média dos seus blocos (✅ Concluído = 100%, ⏳ Parcial = 50%).
    Blocos de lei seca não contam (são leitura de revisão). Se idx_hoje vier, calcula também o
    'esperado': quanto já deveria estar estudado se todos os blocos de antes de hoje estivessem concluídos.
    Retorna lista de dicts por item."""
    por_item = {c: [] for c in ITENS}
    for b in blocos:
        assunto, lei_seca = _assunto(b["nome"])
        if lei_seca:
            continue
        for c in BLOCOS.get((b["materia"], assunto), []):
            esperado = None
            if idx_hoje is not None and b.get("idx") is not None:
                esperado = 1.0 if b["idx"] < idx_hoje else 0.0
            por_item[c].append((CREDITO.get(b["status"], 0.0), esperado, b["nome"], b["status"]))
    linhas = []
    for c, (materia, texto) in ITENS.items():
        bl = por_item[c]
        feito = sum(x[0] for x in bl) / len(bl) if bl else 0.0
        esp = [x[1] for x in bl if x[1] is not None]
        linhas.append({"codigo": c, "materia": materia, "item": texto, "avanco": feito,
                       "esperado": (sum(esp) / len(esp)) if esp else None, "n_blocos": len(bl),
                       "blocos": [(x[2], x[3]) for x in bl]})
    return linhas


def resumo_por_materia(linhas):
    """{matéria: (avanço 0-1, esperado 0-1 ou None, nº itens, itens completos)} – cada item com o mesmo peso."""
    res = {}
    for m in QUESTOES_PROVA:
        its = [l for l in linhas if l["materia"] == m]
        if not its:
            continue
        av = sum(l["avanco"] for l in its) / len(its)
        es = [l["esperado"] for l in its if l["esperado"] is not None]
        res[m] = (av, (sum(es) / len(es)) if es else None, len(its), sum(1 for l in its if l["avanco"] >= 0.999))
    return res


def avanco_global(resumo, ponderado=True):
    """Avanço total: ponderado pelas questões de cada matéria na prova (ou média simples das matérias)."""
    pesos = {m: (QUESTOES_PROVA[m] if ponderado else 1) for m in resumo}
    tot = sum(pesos.values())
    av = sum(resumo[m][0] * pesos[m] for m in resumo) / tot if tot else 0.0
    com_esp = [m for m in resumo if resumo[m][1] is not None]
    tot_e = sum(pesos[m] for m in com_esp)
    es = sum(resumo[m][1] * pesos[m] for m in com_esp) / tot_e if tot_e else None
    return av, es
