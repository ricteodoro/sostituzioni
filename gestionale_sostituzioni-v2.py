import streamlit as st
import pandas as pd
import csv
import re

# Configurazione della pagina Streamlit
st.set_page_config(
    page_title="Gestione Sostituzioni Scolastiche",
    page_icon="🏫",
    layout="wide"
)

# Gestione Accesso con Password
PASSWORD_CORRETTA = "sostituzioni"

if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔒 Accesso Riservato - Gestione Sostituzioni")
    st.markdown("Inserisci la password dell'istituto per accedere al sistema di gestione delle supplenze.")
    
    col_pwd, _ = st.columns([1, 2])
    with col_pwd:
        password_input = st.text_input("Password:", type="password")
        if st.button("🔓 Accedi"):
            if password_input == PASSWORD_CORRETTA:
                st.session_state.authenticated = True
                st.success("Accesso autorizzato!")
                st.rerun()
            else:
                st.error("Password errata. Riprova.")
    st.stop()

# Tasto di Logout nella sidebar
if st.sidebar.button("🔒 Esci (Logout)"):
    st.session_state.authenticated = False
    st.rerun()

st.title("🏫 Gestione Sostituzioni Scolastiche - Web App")
st.markdown("Applicazione per la ricerca e l'assegnazione delle supplenze basata sull'orario scolastico e sulle regole dell'istituto.")

# Funzione per il parsing dell'orario scolastico dal file CSV
@st.cache_data
def parse_schedule_file(file_content_str):
    blocks = file_content_str.split('DOCENTE: ')
    schedule = {}
    days_list = ['Lunedì', 'Martedì', 'Mercoledì', 'Giovedì', 'Venerdì']

    for block in blocks[1:]:
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if not lines:
            continue
        teacher_name = lines[0].split('(')[0].strip().upper()
        schedule[teacher_name] = {d: {h: '' for h in range(1, 7)} for d in days_list}
        
        header_idx = -1
        for idx, line in enumerate(lines):
            if 'Lunedì' in line or 'Martedì' in line:
                header_idx = idx
                break
        
        if header_idx != -1:
            for line in lines[header_idx+1:]:
                parts = [p.strip().strip('\"').strip() for p in line.split(';')]
                if not parts:
                    continue
                ora_str = parts[0]
                m = re.search(r'(\d)ª', ora_str)
                if m:
                    ora_num = int(m.group(1))
                    for day_idx, day_name in enumerate(days_list):
                        if day_idx + 1 < len(parts):
                            val = parts[day_idx + 1]
                            schedule[teacher_name][day_name][ora_num] = val

    return schedule

def get_first_last_scheduled_hour(teacher_schedule_day):
    hours_with_activity = []
    for h in range(1, 7):
        val = teacher_schedule_day.get(h, '').strip().lower()
        if val and val != '-' and val != 'x':
            hours_with_activity.append(h)
    if not hours_with_activity:
        return None, None, 0
    return min(hours_with_activity), max(hours_with_activity), len(hours_with_activity)

def find_substitutes(sched, absent_teacher, day, hour, target_class, existing_assignments):
    candidates = []
    
    for tname, t_days in sched.items():
        if tname == absent_teacher:
            continue
        
        cell_val = t_days[day][hour].strip()
        cell_val_lower = cell_val.lower()
        
        # 1. Esclusione se presente 'x'
        if cell_val_lower == 'x':
            continue
        
        # 2. Regola speciale per TERESA e SCARNERA (possono fare supplenza SOLO su 'p')
        if tname in ['TERESA', 'SCARNERA']:
            if cell_val_lower != 'p':
                continue
        
        # 3. Limite massimo 5 ore giornaliere totali (lezioni + supplenze già assegnate)
        first_h, last_h, count_h = get_first_last_scheduled_hour(t_days[day])
        extra_assigned_today = sum(1 for a in existing_assignments if a['Docente Sostituto'] == tname and a['Giorno'] == day)
        total_hours_today = count_h + extra_assigned_today
        
        if total_hours_today >= 5:
            continue
            
        # 4. Limite massimo 2 ore di supplenza nella stessa classe allo stesso docente
        subs_in_this_class = sum(1 for a in existing_assignments if a['Docente Sostituto'] == tname and a['Classe'] == target_class)
        if subs_in_this_class >= 2:
            continue
            
        # 5. Esclusione se già impegnato in lezione di classe
        is_teaching_class = bool(cell_val and cell_val_lower not in ['d', 'p', 'x', '-'])
        if is_teaching_class:
            continue
            
        priority = None
        sub_type = None
        
        # PRIORITÀ 1: Ore di Disposizione (D) o Potenziamento (P)
        if cell_val_lower in ['d', 'p']:
            priority = 1
            sub_type = f"Ora di {cell_val.upper()} (Disposizione/Potenziamento)"
        # PRIORITÀ 2: Ore Buche
        elif cell_val == '' or cell_val == '-':
            # Vincolo ora di ingresso: se entra alla 2ª ora o dopo, non può fare supplenza prima del suo inizio lezione
            if first_h is None or hour < first_h:
                continue
            priority = 2
            sub_type = "Ora Buca (Ora Eccedente / Straordinaria)"
            
        if priority is not None:
            candidates.append({
                'Docente': tname,
                'Priorità': f"Priorità {priority}",
                'Tipo Copertura': sub_type,
                'Stato in Orario': cell_val if cell_val else 'Buca',
                'Ore Lezione Oggi': count_h,
                'Fascia Presenza': f"{first_h}ª - {last_h}ª ora" if first_h else "Nessuna lezione",
                '_priority_num': priority
            })
            
    candidates.sort(key=lambda x: (x['_priority_num'], x['Docente']))
    return candidates

# Inizializzazione registro supplenze in sessione
if 'assignments' not in st.session_state:
    st.session_state.assignments = []

# Sidebar per caricamento orario
st.sidebar.header("📁 Caricamento Orario")
csv_file = st.sidebar.file_uploader("Carica File CSV Orario Scolastico", type=['csv'])

schedule_data = None
if csv_file is not None:
    content = csv_file.getvalue().decode('utf-8-sig', errors='ignore')
    schedule_data = parse_schedule_file(content)
    st.sidebar.success("File CSV caricato correttamente!")
else:
    try:
        with open('orario_scolastico_def1(6).csv', 'r', encoding='utf-8-sig', errors='ignore') as f:
            content = f.read()
            schedule_data = parse_schedule_file(content)
            st.sidebar.info("Orario predefinito caricato.")
    except Exception:
        st.sidebar.warning("Carica il file CSV dell'orario per iniziare.")

if schedule_data:
    teachers_list = sorted(list(schedule_data.keys()))
    days_list = ['Lunedì', 'Martedì', 'Mercoledì', 'Giovedì', 'Venerdì']
    hours_list = [1, 2, 3, 4, 5, 6]

    st.subheader("🔍 Ricerca Sostituto per Docente Assente")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        absent_teacher = st.selectbox("Docente Assente", teachers_list)
    with col2:
        selected_day = st.selectbox("Giorno Assenza", days_list)
    with col3:
        selected_hour = st.selectbox("Ora Assenza", hours_list, format_func=lambda h: f"{h}ª Ora")
    
    current_class_scheduled = schedule_data[absent_teacher][selected_day][selected_hour].strip()
    with col4:
        target_class = st.text_input("Classe da Coprire", value=current_class_scheduled if current_class_scheduled else "Es. 1C")

    candidates = find_substitutes(schedule_data, absent_teacher, selected_day, selected_hour, target_class, st.session_state.assignments)

    st.markdown("### 📋 Elenco Docenti Disponibili (Ordinati per Criteri di Priorità)")
    
    if candidates:
        df_candidates = pd.DataFrame(candidates).drop(columns=['_priority_num'])
        st.dataframe(df_candidates, use_container_width=True)

        st.markdown("### ✍️ Assegnazione Supplenza (Consigliata o Manuale)")
        
        candidate_names = [c['Docente'] for c in candidates]
        col_assign1, col_assign2, col_assign3 = st.columns([2, 2, 1])
        
        with col_assign1:
            assign_mode = st.radio("Modalità Selezione", ["Da Suggeriti (Consigliati)", "Assegnazione Manuale Libera"])
            
        with col_assign2:
            if assign_mode == "Da Suggeriti (Consigliati)":
                chosen_teacher = st.selectbox("Seleziona Sostituto", candidate_names)
            else:
                chosen_teacher = st.selectbox("Seleziona Docente Manualmente", teachers_list)
                
        with col_assign3:
            st.write("")
            st.write("")
            if st.button("➕ Assegna Supplenza"):
                cand_info = next((c for c in candidates if c['Docente'] == chosen_teacher), None)
                if cand_info:
                    c_type = cand_info['Tipo Copertura']
                else:
                    c_type = "Assegnazione Manuale Straordinaria"
                    
                new_sub = {
                    "Giorno": selected_day,
                    "Ora": f"{selected_hour}ª Ora",
                    "Docente Assente": absent_teacher,
                    "Classe": target_class,
                    "Docente Sostituto": chosen_teacher,
                    "Tipo Copertura": c_type,
                    "Ora Eccedente (Pagamento/Recupero)": "SÌ" if "Ora Buca" in c_type or "Manuale" in c_type else "NO"
                }
                st.session_state.assignments.append(new_sub)
                st.success(f"Supplenza assegnata a {chosen_teacher}!")
                st.rerun()
    else:
        st.warning("Nessun docente idoneo automaticamente per i vincoli impostati. Puoi procedere con l'assegnazione manuale.")
        manual_teacher = st.selectbox("Seleziona Docente Manualmente", teachers_list, key="manual_fallback")
        if st.button("➕ Assegna Manualmente"):
            new_sub = {
                "Giorno": selected_day,
                "Ora": f"{selected_hour}ª Ora",
                "Docente Assente": absent_teacher,
                "Classe": target_class,
                "Docente Sostituto": manual_teacher,
                "Tipo Copertura": "Assegnazione Manuale Straordinaria",
                "Ora Eccedente (Pagamento/Recupero)": "SÌ"
            }
            st.session_state.assignments.append(new_sub)
            st.success(f"Supplenza assegnata manualmente a {manual_teacher}!")
            st.rerun()

    st.markdown("---")
    st.subheader("📑 Registro Supplenze del Giorno e Report Ore Eccedenti")

    if st.session_state.assignments:
        df_assignments = pd.DataFrame(st.session_state.assignments)
        st.dataframe(df_assignments, use_container_width=True)

        df_eccedenti = df_assignments[df_assignments["Ora Eccedente (Pagamento/Recupero)"] == "SÌ"]
        
        st.markdown("#### 💰 Report Ore Eccedenti / Straordinarie (Docenti in Ora Buca)")
        if not df_eccedenti.empty:
            summary_eccedenti = df_eccedenti.groupby("Docente Sostituto").size().reset_index(name="Totale Ore Eccedenti")
            st.dataframe(summary_eccedenti, use_container_width=True)
        else:
            st.info("Nessuna ora eccedente accumulata (tutte le sostituzioni finora sono su Disposizione/Potenziamento).")

        col_act1, col_act2 = st.columns(2)
        with col_act1:
            csv_report = df_assignments.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label="📥 Scarica Report Supplenze (CSV)",
                data=csv_report,
                file_name="report_supplenze.csv",
                mime="text/csv"
            )
        with col_act2:
            if st.button("🗑️ Svuota Registro"):
                st.session_state.assignments = []
                st.rerun()
