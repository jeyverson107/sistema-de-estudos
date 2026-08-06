import streamlit as st
import pandas as pd
import datetime
import sqlite3
import time

st.set_page_config(page_title="Sistema de Estudos & Carreira", layout="wide", page_icon="🛡️")

# -----------------------------------------------------------------------------
# BANCO DE DADOS DINÂMICO (SQLite)
# -----------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect("estudos_master.db")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS metas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT UNIQUE,
                    tipo TEXT,
                    ativa INTEGER DEFAULT 1
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS materias (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meta_id INTEGER,
                    nome TEXT,
                    FOREIGN KEY(meta_id) REFERENCES metas(id) ON DELETE CASCADE
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS topicos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    materia_id INTEGER,
                    nome TEXT,
                    teoria INTEGER DEFAULT 0,
                    resumo INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'Pendente',
                    FOREIGN KEY(materia_id) REFERENCES materias(id) ON DELETE CASCADE
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS exercicios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data TEXT,
                    topico_id INTEGER,
                    acertos INTEGER,
                    erros INTEGER,
                    FOREIGN KEY(topico_id) REFERENCES topicos(id) ON DELETE CASCADE
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS configuracoes (
                    chave TEXT PRIMARY KEY,
                    valor TEXT
                )''')
    conn.commit()
    conn.close()

init_db()

# -----------------------------------------------------------------------------
# ALGORITMO DE CÁLCULO DE NÍVEL DE DOMÍNIO
# -----------------------------------------------------------------------------
def calcular_nivel_materia(materia_id, conn):
    query_topicos = "SELECT status FROM topicos WHERE materia_id = ?"
    df_topicos = pd.read_sql_query(query_topicos, conn, params=(int(materia_id),))
    
    if df_topicos.empty:
        return 5.0
        
    total_topicos = len(df_topicos)
    concluidos = len(df_topicos[df_topicos['status'] == 'Concluído'])
    parciais = len(df_topicos[df_topicos['status'] == 'Parcial'])
    
    pct_teoria = ((concluidos + (0.5 * parciais)) / total_topicos) * 10.0
    
    query_ex = """
        SELECT e.acertos, e.erros 
        FROM exercicios e
        JOIN topicos t ON e.topico_id = t.id
        WHERE t.materia_id = ?
    """
    df_ex = pd.read_sql_query(query_ex, conn, params=(int(materia_id),))
    
    if df_ex.empty:
        return round(pct_teoria, 1)
        
    total_acertos = df_ex['acertos'].sum()
    total_erros = df_ex['erros'].sum()
    total_q = total_acertos + total_erros
    
    if total_q == 0:
        return round(pct_teoria, 1)
        
    taxa_acerto = total_acertos / total_q
    score_pratica = taxa_acerto * 10.0
    
    peso_questoes = min(1.0, total_q / 30.0) * 0.6
    peso_teoria = 1.0 - peso_questoes
    
    nivel_calculado = (pct_teoria * peso_teoria) + (score_pratica * peso_questoes)
    return round(nivel_calculado, 1)

def get_config(chave, valor_padrao):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT valor FROM configuracoes WHERE chave = ?", (chave,))
    res = c.fetchone()
    conn.close()
    return res[0] if res else valor_padrao

def set_config(chave, valor):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO configuracoes (chave, valor) VALUES (?, ?)", (chave, str(valor)))
    conn.commit()
    conn.close()

# -----------------------------------------------------------------------------
# INTERFACE PRINCIPAL
# -----------------------------------------------------------------------------
st.title("🛡️ Sistema Unificado de Gestão de Estudos")

menu = st.sidebar.radio("Navegação", [
    "📅 Meta & Rotina do Dia", 
    "📋 Checklist & Acompanhamento", 
    "📝 Registrar Questões", 
    "📊 Dashboard de Evolução", 
    "⚙️ Gerenciador & Importador Excel"
])

conn = get_db()

# =============================================================================
# MENU 1: META & ROTINA DO DIA (COM CRONÔMETRO INTEGRADO)
# =============================================================================
if menu == "📅 Meta & Rotina do Dia":
    st.header("🎯 Sugestão Diária de Estudo e Rotina Policial")
    
    escalado = st.checkbox("🚨 Estarei Escalado Hoje / Plantão Extra (Suspender estudos hoje)", value=False)
    
    if escalado:
        st.warning("⚠️ **Modo Plantão/Escala Ativado:** O ciclo de estudos foi pausado para hoje. Bons serviços no plantão!")
    else:
        horas_disp = float(get_config("horas_estudo_dia", "3.0"))
        turno_pref = get_config("turno_estudo", "Noite")
        
        st.info(f"💡 **Disponibilidade Hoje:** {horas_disp} horas no turno da **{turno_pref}**.")
        
        df_metas = pd.read_sql_query("SELECT id, nome FROM metas WHERE ativa = 1", conn)
        
        if df_metas.empty:
            st.warning("Nenhum objetivo cadastrado. Cadastre um em '⚙️ Gerenciador'.")
        else:
            meta_sel_rotina = st.selectbox("Selecione o Objetivo do Dia:", df_metas['nome'].tolist())
            meta_id_rotina = df_metas[df_metas['nome'] == meta_sel_rotina]['id'].values[0]
            
            query_proximos = """
                SELECT t.id as topico_id, t.nome as topico_nome, m.id as materia_id, m.nome as materia_nome, t.status
                FROM topicos t
                JOIN materias m ON t.materia_id = m.id
                WHERE m.meta_id = ? AND t.status != 'Concluído'
                ORDER BY m.id, t.id
            """
            df_proximos = pd.read_sql_query(query_proximos, conn, params=(int(meta_id_rotina),))
            
            if df_proximos.empty:
                st.balloons()
                st.success("🎉 Parabéns! Todos os tópicos deste objetivo foram concluídos!")
            else:
                topicos_sugeridos = df_proximos.groupby('materia_nome').first().reset_index().head(2)
                
                niveis = []
                pesos = []
                for idx, row in topicos_sugeridos.iterrows():
                    nv = calcular_nivel_materia(row['materia_id'], conn)
                    niveis.append(nv)
                    pesos.append(max(1.0, 11.0 - nv))
                
                soma_pesos = sum(pesos)
                
                st.subheader("📌 Recomendações e Cronômetro de Estudo:")
                
                for i, (_, row) in enumerate(topicos_sugeridos.iterrows()):
                    prop_tempo = pesos[i] / soma_pesos
                    tempo_horas = horas_disp * prop_tempo
                    total_segundos = int(tempo_horas * 3600)
                    
                    horas_f = int(tempo_horas)
                    minutos_f = int(round((tempo_horas - horas_f) * 60))
                    tempo_str = f"{horas_f}h{minutos_f:02d}m" if horas_f > 0 else f"{minutos_f} min"
                    
                    topico_key = f"timer_{row['topico_id']}"
                    
                    # Inicialização do estado do cronômetro para cada tópico
                    if f"{topico_key}_restante" not in st.session_state:
                        st.session_state[f"{topico_key}_restante"] = total_segundos
                    if f"{topico_key}_ativo" not in st.session_state:
                        st.session_state[f"{topico_key}_ativo"] = False

                    with st.expander(f"📖 **{row['materia_nome']}** | Tempo Adaptativo: **{tempo_str}** | Domínio: `{niveis[i]}/10`", expanded=True):
                        st.markdown(f"**Conteúdo Específico:** {row['topico_nome']}")
                        st.write(f"**Status Atual:** `{row['status']}`")
                        
                        # --- Bloco do Cronômetro ---
                        st.markdown("---")
                        st.markdown("#### ⏱️ Cronômetro de Estudo")
                        
                        seg_restantes = st.session_state[f"{topico_key}_restante"]
                        hrs_c = seg_restantes // 3600
                        mins_c = (seg_restantes % 3600) // 60
                        secs_c = seg_restantes % 60
                        
                        timer_display = st.empty()
                        timer_display.markdown(f"### ⏳ `{hrs_c:02d}:{mins_c:02d}:{secs_c:02d}`")
                        
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            if st.button("▶️ Iniciar / Continuar", key=f"start_{row['topico_id']}"):
                                st.session_state[f"{topico_key}_ativo"] = True
                        with c2:
                            if st.button("⏸️ Pausar", key=f"pause_{row['topico_id']}"):
                                st.session_state[f"{topico_key}_ativo"] = False
                        with c3:
                            if st.button("🔄 Reiniciar Tempo", key=f"reset_{row['topico_id']}"):
                                st.session_state[f"{topico_key}_ativo"] = False
                                st.session_state[f"{topico_key}_restante"] = total_segundos
                                st.rerun()

                        # Loop do Cronômetro em Tempo Real
                        if st.session_state[f"{topico_key}_ativo"]:
                            while st.session_state[f"{topico_key}_restante"] > 0 and st.session_state[f"{topico_key}_ativo"]:
                                time.sleep(1)
                                st.session_state[f"{topico_key}_restante"] -= 1
                                r_seg = st.session_state[f"{topico_key}_restante"]
                                r_h = r_seg // 3600
                                r_m = (r_seg % 3600) // 60
                                r_s = r_seg % 60
                                timer_display.markdown(f"### ⏳ `{r_h:02d}:{r_m:02d}:{r_s:02d}`")
                                
                                if st.session_state[f"{topico_key}_restante"] == 0:
                                    st.session_state[f"{topico_key}_ativo"] = False
                                    st.balloons()
                                    st.success("🔔 **Tempo encerrado!** Ótimo trabalho de estudo!")
                                    st.rerun()

                        st.markdown("---")
                        
                        # --- Finalização da Matéria ---
                        col_a, col_b = st.columns(2)
                        with col_a:
                            if st.button(f"✅ Concluído Totalmente", key=f"conc_{row['topico_id']}"):
                                c = conn.cursor()
                                c.execute("UPDATE topicos SET status = 'Concluído', teoria = 1 WHERE id = ?", (int(row['topico_id']),))
                                conn.commit()
                                st.session_state[f"{topico_key}_restante"] = total_segundos
                                st.session_state[f"{topico_key}_ativo"] = False
                                st.success("Tópico Concluído!")
                                st.rerun()
                        with col_b:
                            if st.button(f"⏳ Parcialmente Estudado", key=f"parc_{row['topico_id']}"):
                                c = conn.cursor()
                                c.execute("UPDATE topicos SET status = 'Parcial' WHERE id = ?", (int(row['topico_id']),))
                                conn.commit()
                                st.session_state[f"{topico_key}_restante"] = total_segundos
                                st.session_state[f"{topico_key}_ativo"] = False
                                st.info("Marcado como Parcial.")
                                st.rerun()

# =============================================================================
# MENU 2: CHECKLIST & ACOMPANHAMENTO
# =============================================================================
elif menu == "📋 Checklist & Acompanhamento":
    st.header("📋 Checklist de Conteúdos por Matéria")
    
    df_metas = pd.read_sql_query("SELECT id, nome FROM metas WHERE ativa = 1", conn)
    
    if df_metas.empty:
        st.info("Nenhum objetivo cadastrado.")
    else:
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            meta_sel = st.selectbox("1. Selecione o Objetivo", df_metas['nome'].tolist())
            meta_id = df_metas[df_metas['nome'] == meta_sel]['id'].values[0]
        
        df_mat = pd.read_sql_query("SELECT id, nome FROM materias WHERE meta_id = ?", conn, params=(int(meta_id),))
        
        if df_mat.empty:
            st.warning("Nenhuma matéria cadastrada para este objetivo.")
        else:
            with col_m2:
                mat_sel = st.selectbox("2. Filtrar por Matéria", df_mat['nome'].tolist())
                mat_id = df_mat[df_mat['nome'] == mat_sel]['id'].values[0]
            
            nivel_atual = calcular_nivel_materia(mat_id, conn)
            st.info(f"📊 **Nível de Domínio Calculado em {mat_sel}:** `{nivel_atual} / 10.0`")
            
            query = """
                SELECT id, nome as Topico, teoria as Videoaula_PDF, resumo as Resumo_Mapa, status as Status
                FROM topicos
                WHERE materia_id = ?
            """
            df_topicos = pd.read_sql_query(query, conn, params=(int(mat_id),))
            
            if df_topicos.empty:
                st.info("Nenhum tópico cadastrado nesta matéria.")
            else:
                df_topicos['Videoaula_PDF'] = df_topicos['Videoaula_PDF'].astype(bool)
                df_topicos['Resumo_Mapa'] = df_topicos['Resumo_Mapa'].astype(bool)
                
                edited_df = st.data_editor(
                    df_topicos[['id', 'Topico', 'Videoaula_PDF', 'Resumo_Mapa', 'Status']],
                    column_config={
                        "Videoaula_PDF": st.column_config.CheckboxColumn("Teoria"),
                        "Resumo_Mapa": st.column_config.CheckboxColumn("Resumo/Mapa"),
                        "Status": st.column_config.SelectboxColumn(
                            "Status de Conclusão",
                            options=["Pendente", "Parcial", "Concluído"],
                            required=True
                        )
                    },
                    disabled=["id", "Topico"],
                    hide_index=True,
                    use_container_width=True
                )
                
                if st.button("💾 Salvar Alterações na Matéria"):
                    c = conn.cursor()
                    for idx, row in edited_df.iterrows():
                        c.execute("""
                            UPDATE topicos 
                            SET teoria = ?, resumo = ?, status = ? 
                            WHERE id = ?
                        """, (
                            1 if row['Videoaula_PDF'] else 0,
                            1 if row['Resumo_Mapa'] else 0,
                            row['Status'],
                            int(row['id'])
                        ))
                    conn.commit()
                    st.success("Progresso salvo com sucesso!")
                    st.rerun()

# =============================================================================
# MENU 3: REGISTRAR QUESTÕES
# =============================================================================
elif menu == "📝 Registrar Questões":
    st.header("📝 Registro de Desempenho em Exercícios")
    
    df_metas = pd.read_sql_query("SELECT id, nome FROM metas WHERE ativa = 1", conn)
    
    if df_metas.empty:
        st.warning("Cadastre um Objetivo e Matérias no menu '⚙️ Gerenciador' antes de lançar exercícios.")
    else:
        meta_sel = st.selectbox("Selecione o Objetivo", df_metas['nome'].tolist())
        meta_id = df_metas[df_metas['nome'] == meta_sel]['id'].values[0]
        
        df_mat = pd.read_sql_query("SELECT id, nome FROM materias WHERE meta_id = ?", conn, params=(int(meta_id),))
        
        if df_mat.empty:
            st.warning("Nenhuma matéria cadastrada para este objetivo.")
        else:
            mat_sel = st.selectbox("Selecione a Matéria", df_mat['nome'].tolist())
            mat_id = df_mat[df_mat['nome'] == mat_sel]['id'].values[0]
            
            df_top = pd.read_sql_query("SELECT id, nome FROM topicos WHERE materia_id = ?", conn, params=(int(mat_id),))
            
            if df_top.empty:
                st.warning("Nenhum tópico cadastrado nesta matéria.")
            else:
                topico_sel = st.selectbox("Selecione o Tópico", df_top['nome'].tolist())
                topico_id = df_top[df_top['nome'] == topico_sel]['id'].values[0]
                
                with st.form("form_ex"):
                    col_a, col_b = st.columns(2)
                    with col_a: acertos = st.number_input("Número de Acertos", min_value=0, value=10)
                    with col_b: erros = st.number_input("Número de Erros", min_value=0, value=2)
                    
                    if st.form_submit_button("Salvar Desempenho"):
                        c = conn.cursor()
                        c.execute("INSERT INTO exercicios (data, topico_id, acertos, erros) VALUES (?, ?, ?, ?)",
                                  (datetime.date.today().strftime('%Y-%m-%d'), int(topico_id), acertos, erros))
                        conn.commit()
                        st.success("Exercícios registrados com sucesso!")
                        st.rerun()

# =============================================================================
# MENU 4: DASHBOARD DE EVOLUÇÃO
# =============================================================================
elif menu == "📊 Dashboard de Evolução":
    st.header("📊 Dashboard Geral de Desempenho")
    
    df_metas = pd.read_sql_query("SELECT id, nome FROM metas WHERE ativa = 1", conn)
    
    if df_metas.empty:
        st.warning("Nenhum objetivo ativo para gerar relatórios.")
    else:
        tabs = st.tabs(df_metas['nome'].tolist())
        
        for idx, row_meta in df_metas.iterrows():
            with tabs[idx]:
                m_id = row_meta['id']
                df_mats = pd.read_sql_query("SELECT id, nome FROM materias WHERE meta_id = ?", conn, params=(int(m_id),))
                
                if df_mats.empty:
                    st.info("Sem matérias cadastradas.")
                else:
                    niveis_lista = []
                    for _, r_mat in df_mats.iterrows():
                        nv = calcular_nivel_materia(r_mat['id'], conn)
                        niveis_lista.append({"Matéria": r_mat['nome'], "Nível Domínio": nv})
                    
                    df_niv = pd.DataFrame(niveis_lista)
                    media_geral = df_niv['Nível Domínio'].mean()
                    
                    q_top = "SELECT t.status FROM topicos t JOIN materias m ON t.materia_id = m.id WHERE m.meta_id = ?"
                    df_top_meta = pd.read_sql_query(q_top, conn, params=(int(m_id),))
                    total_t = len(df_top_meta)
                    conc_t = len(df_top_meta[df_top_meta['status'] == 'Concluído'])
                    pct = (conc_t / total_t * 100) if total_t > 0 else 0
                    
                    col_x, col_y, col_z = st.columns(3)
                    col_x.metric("Avanço do Edital", f"{pct:.1f}%", f"{conc_t}/{total_t} concluídos")
                    col_y.metric("Domínio Médio Geral", f"{media_geral:.1f} / 10")
                    col_z.progress(pct / 100)
                    
                    st.subheader("🎯 Nível de Domínio Calculado por Matéria")
                    st.dataframe(df_niv, use_container_width=True, hide_index=True)

# =============================================================================
# MENU 5: GERENCIADOR & CONFIGURAÇÕES
# =============================================================================
elif menu == "⚙️ Gerenciador & Importador Excel":
    st.header("⚙️ Gerenciador do Sistema")
    
    t0, t1, t2, t3, t4 = st.tabs([
        "⚙️ Disp. de Tempo", 
        "1. Objetivos", 
        "2. Matérias", 
        "3. Tópicos", 
        "4. 📥 Importar Excel"
    ])
    
    with t0:
        st.subheader("Configurar Disponibilidade Diária de Estudos")
        hor_atual = float(get_config("horas_estudo_dia", "3.0"))
        tur_atual = get_config("turno_estudo", "Noite")
        
        with st.form("form_disp"):
            novas_horas = st.number_input("Horas disponíveis por dia:", min_value=0.5, max_value=12.0, value=hor_atual, step=0.5)
            novo_turno = st.selectbox("Turno Principal:", ["Manhã", "Tarde", "Noite"], index=["Manhã", "Tarde", "Noite"].index(tur_atual))
            
            if st.form_submit_button("Salvar Horários"):
                set_config("horas_estudo_dia", novas_horas)
                set_config("turno_estudo", novo_turno)
                st.success("Configurações salvas!")
                st.rerun()

    with t1:
        st.subheader("Cadastrar Novo Objetivo")
        with st.form("f_meta"):
            n_meta = st.text_input("Nome do Objetivo (Ex: Concurso PMPE, Faculdade UPE)")
            tipo_meta = st.selectbox("Tipo", ["Concurso", "Faculdade", "Outro"])
            if st.form_submit_button("Adicionar Objetivo"):
                if n_meta.strip() != "":
                    try:
                        c = conn.cursor()
                        c.execute("INSERT INTO metas (nome, tipo) VALUES (?, ?)", (n_meta.strip(), tipo_meta))
                        conn.commit()
                        st.success(f"Objetivo '{n_meta}' adicionado!")
                        st.rerun()
                    except:
                        st.error("Esse objetivo já existe.")

    with t2:
        df_m = pd.read_sql_query("SELECT id, nome FROM metas", conn)
        if df_m.empty:
            st.warning("Cadastre um objetivo primeiro.")
        else:
            st.subheader("Cadastrar Nova Matéria")
            sel_m_mat = st.selectbox("Vincular ao Objetivo:", df_m['nome'].tolist(), key="sb_m_mat")
            m_id_sel = df_m[df_m['nome'] == sel_m_mat]['id'].values[0]
            
            with st.form("f_mat"):
                n_materia = st.text_input("Nome da Matéria (Ex: Direito Administrativo)")
                if st.form_submit_button("Adicionar Matéria"):
                    if n_materia.strip() != "":
                        c = conn.cursor()
                        c.execute("INSERT INTO materias (meta_id, nome) VALUES (?, ?)", (int(m_id_sel), n_materia.strip()))
                        conn.commit()
                        st.success(f"Matéria '{n_materia}' adicionada!")
                        st.rerun()

    with t3:
        df_mat_all = pd.read_sql_query("""
            SELECT m.id as mat_id, m.nome as mat_nome, meta.nome as meta_nome 
            FROM materias m 
            JOIN metas meta ON m.meta_id = meta.id
        """, conn)
        
        if df_mat_all.empty:
            st.warning("Cadastre matérias primeiro.")
        else:
            st.subheader("Cadastrar Tópico Individual")
            options_mat = [f"{r['meta_nome']} -> {r['mat_nome']}" for i, r in df_mat_all.iterrows()]
            sel_mat_top = st.selectbox("Selecione a Matéria:", options_mat)
            idx_mat_sel = options_mat.index(sel_mat_top)
            target_mat_id = df_mat_all.iloc[idx_mat_sel]['mat_id']
            
            with st.form("f_topico"):
                n_topico = st.text_input("Descrição do Tópico")
                if st.form_submit_button("Adicionar Tópico"):
                    if n_topico.strip() != "":
                        c = conn.cursor()
                        c.execute("INSERT INTO topicos (materia_id, nome) VALUES (?, ?)", 
                                  (int(target_mat_id), n_topico.strip()))
                        conn.commit()
                        st.success("Tópico adicionado com sucesso!")
                        st.rerun()

    with t4:
        st.subheader("📥 Importar Planilha Excel (`.xlsx`)")
        df_m = pd.read_sql_query("SELECT id, nome FROM metas WHERE ativa = 1", conn)
        
        if df_m.empty:
            st.warning("Cadastre primeiro um Objetivo na Aba 1 antes de importar.")
        else:
            meta_excel_sel = st.selectbox("Vincular os dados desta planilha ao Objetivo:", df_m['nome'].tolist())
            meta_excel_id = df_m[df_m['nome'] == meta_excel_sel]['id'].values[0]
            
            uploaded_file = st.file_uploader("Selecione o arquivo Excel", type=["xlsx"])
            
            if uploaded_file is not None:
                try:
                    xls = pd.ExcelFile(uploaded_file)
                    st.success(f"Planilha reconhecida! Abas: {', '.join(xls.sheet_names)}")
                    
                    if st.button("🚀 Processar e Importar Tudo"):
                        c = conn.cursor()
                        total_m_count = 0
                        total_t_count = 0
                        
                        for sheet in xls.sheet_names:
                            if sheet.upper() == "DASHBOARD":
                                continue
                            
                            df_sheet = pd.read_excel(uploaded_file, sheet_name=sheet)
                            mat_nome = sheet.strip().upper()
                            
                            c.execute("SELECT id FROM materias WHERE meta_id = ? AND UPPER(nome) = ?", (int(meta_excel_id), mat_nome))
                            res_mat = c.fetchone()
                            if res_mat:
                                mat_id = res_mat[0]
                            else:
                                c.execute("INSERT INTO materias (meta_id, nome) VALUES (?, ?)", (int(meta_excel_id), mat_nome))
                                mat_id = c.lastrowid
                                total_m_count += 1
                            
                            for idx, row in df_sheet.iterrows():
                                if idx == 0 or pd.isna(row.iloc[2]): 
                                    continue
                                
                                topico_desc = str(row.iloc[2]).strip()
                                c.execute("INSERT INTO topicos (materia_id, nome) VALUES (?, ?)", (int(mat_id), topico_desc))
                                total_t_count += 1
                        
                        conn.commit()
                        st.success(f"🎉 Importação concluída! {total_m_count} matérias e {total_t_count} tópicos salvos.")
                        st.rerun()
                except Exception as e:
                    st.error(f"Erro ao processar a planilha: {e}")

conn.close()
