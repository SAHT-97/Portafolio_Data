import streamlit as st
import pdfplumber
import pandas as pd
import io
import re
from datetime import datetime

# ==========================================
# 1. CONFIGURACIÓN
# ==========================================
st.set_page_config(page_title="F-29 Analytics", page_icon="🤖", layout="wide")

# ==========================================
# 2. DEFINICIÓN DE ETIQUETAS (MAYÚSCULAS)
# ==========================================
MAPA_ETIQUETAS = {
    # --- CANTIDADES (FORMATO NÚMERO) ---
    503: "CANTIDAD FACTURAS EMITIDAS [503]",
    110: "CANT. DE DCTOS. BOLETAS [110]",
    584: "CANT. INT. EX. NO GRAV. SIN DER. CRED. FISCAL [584]",
    519: "CANT. DE DCTOS. FACT. RECIB. DEL GIRO [519]",
    527: "CANT. NOTAS DE CRÉDITO RECIBIDAS [527]",
    
    # --- TASAS (FORMATO %) ---
    115: "TASA PPM 1RA. CATEGORÍA [115]",
    
    # --- MONTOS (FORMATO PESOS) ---
    511: "CRÉD. IVA POR DCTOS. ELECTRÓNICOS [511]",
    77:  "REMANENTE DE CRÉDITO FISC. [77]",
    563: "BASE IMPONIBLE [563]",
    502: "DÉBITOS FACTURAS EMITIDAS [502]",
    111: "DÉBITOS / BOLETAS [111]",
    538: "TOTAL DÉBITOS [538]",
    520: "CRÉDITO REC. Y REINT./FACT. DEL GIRO [520]",
    504: "REMANENTE CRÉDITO MES ANTERIOR [504]",
    544: "RECUP. IMP. ESP. DIESEL (ART. 2) [544]",
    779: "MONTO DE IVA POSTERGADO 6 O 12 CUOTAS [779]",
    537: "TOTAL CRÉDITOS [537]",
    89:  "IMP. DETERM. IVA [89]",
    62:  "PPM NETO DETERMINADO [62]",
    595: "SUB TOTAL IMP. DETERMINADO ANVERSO [595]",
    547: "TOTAL DETERMINADO [547]",
    91:  "TOTAL A PAGAR DENTRO DEL PLAZO LEGAL [91]",
    92:  "MÁS IPC [92]",
    93:  "MÁS INTERES Y MULTAS [93]",
    795: "CONDONACIÓN [795]",
    94:  "TOTAL A PAGAR CON RECARGO [94]",
    
    # --- EXTRAS ---
    562: "MONTO SIN DER. A CRED. FISCAL [562]",
    528: "CRÉDITO RECUP. Y REINT NOTAS DE CRED [528]"
}

# Listas de control para el formateo
CODIGOS_ENTERO = [584, 519, 527, 503, 110]
CODIGOS_PORCENTAJE = [115]

# ==========================================
# 3. LÓGICA DE EXTRACCIÓN
# ==========================================

def limpiar_numero(valor_texto):
    try:
        if not valor_texto: return 0
        val_str = str(valor_texto).replace('.', '').replace(' ', '').strip()
        val_str = val_str.replace(',', '') 
        if not val_str or not re.match(r'^-?\d+$', val_str):
            return 0
        return int(val_str)
    except:
        return 0

def match_codigo(texto_pdf, codigo_buscado):
    try:
        return int(texto_pdf) == int(codigo_buscado)
    except:
        return False

def extraer_valor_cuadrante(pagina, codigo_buscado, es_total=False):
    words = pagina.extract_words()
    ancho_pagina = pagina.width
    mitad_pagina = ancho_pagina / 2
    
    codigo_obj = None
    for word in words:
        if match_codigo(word['text'], codigo_buscado):
            codigo_obj = word
            break
            
    if not codigo_obj: return 0

    x_inicio = codigo_obj['x1']
    esta_a_la_izquierda = codigo_obj['x0'] < mitad_pagina
    
    if es_total:
        x_fin = ancho_pagina
    else:
        if esta_a_la_izquierda:
            x_fin = mitad_pagina + 15 
        else:
            x_fin = ancho_pagina
    
    candidatos = []
    y_mid = (codigo_obj['top'] + codigo_obj['bottom']) / 2
    
    for word in words:
        if word == codigo_obj: continue
        word_mid = (word['top'] + word['bottom']) / 2
        if abs(word_mid - y_mid) > 6: continue
        if word['x0'] >= x_inicio and word['x1'] <= x_fin:
            candidatos.append(word)
            
    if not candidatos: return 0
    candidatos.sort(key=lambda w: w['x0'])
    
    for word in reversed(candidatos):
        txt = word['text']
        if re.match(r'^[\d\.]+$', txt.replace(' ', '')):
            return limpiar_numero(txt)
    return 0

def extraer_datos_pie_pagina_tablas(pagina):
    tipo_decl = "NO DETECTADO"
    fecha_pres = "NO DETECTADA"
    try:
        tablas = pagina.extract_tables()
        for tabla in tablas:
            for i, fila in enumerate(tabla):
                fila_str = [str(c).strip() if c else "" for c in fila]
                
                indices_tipo = [idx for idx, val in enumerate(fila_str) if "Tipo de Declaración" in val]
                if indices_tipo and i + 1 < len(tabla):
                    val = tabla[i+1][indices_tipo[0]]
                    if val: tipo_decl = val.strip().upper() # Forzar mayúsculas

                indices_fecha = [idx for idx, val in enumerate(fila_str) if "Fecha de Presentación" in val]
                if indices_fecha and i + 1 < len(tabla):
                    val = tabla[i+1][indices_fecha[0]]
                    if val and re.search(r'\d{2}/\d{2}/\d{4}', val):
                        fecha_pres = val.strip()

        if tipo_decl == "NO DETECTADO" or fecha_pres == "NO DETECTADA":
            texto = pagina.crop((0, pagina.height * 0.70, pagina.width, pagina.height)).extract_text()
            if texto:
                if fecha_pres == "NO DETECTADA":
                    match = re.search(r'(\d{2}/\d{2}/\d{4})', texto)
                    if match: fecha_pres = match.group(1)
                if tipo_decl == "NO DETECTADO":
                    if "Primitiva" in texto: tipo_decl = "PRIMITIVA"
                    elif "Rectificatoria" in texto: tipo_decl = "RECTIFICATORIA"
    except: pass
    return tipo_decl, fecha_pres

def obtener_nombre_periodo_sortable(texto_periodo, nombre_archivo=""):
    try:
        s_valor = str(texto_periodo).strip()
        match = re.search(r'(20\d{2})(0[1-9]|1[0-2])', s_valor)
        if match:
            anio, mes = int(match.group(1)), int(match.group(2))
            mapa = {1:"ENE", 2:"FEB", 3:"MAR", 4:"ABR", 5:"MAY", 6:"JUN", 
                    7:"JUL", 8:"AGO", 9:"SEP", 10:"OCT", 11:"NOV", 12:"DIC"}
            return datetime(anio, mes, 1), f"{mapa.get(mes)} {anio}"
    except: pass
    return datetime(1900,1,1), f"MANUAL ({nombre_archivo})"

def recuperar_periodo_regex(pagina):
    try:
        texto = pagina.crop((0, 0, pagina.width, 300)).extract_text()
        match = re.search(r'\b(20\d{2})(0[1-9]|1[0-2])\b', texto)
        if match: return match.group(0)
    except: pass
    return "0"

def procesar_pdfs_logica(archivos):
    # Lista de códigos completa
    codigos_columna = [503, 110, 511, 584, 519, 527, 77, 563, 115, 
                       502, 111, 538, 562, 520, 528, 504, 544, 779, 537, 
                       89, 62, 595, 547]
    codigos_totales = [91, 92, 93, 795, 94]
    
    lista_datos = []
    nombres_vistos = {}
    progreso = st.progress(0)
    
    for i, archivo in enumerate(archivos):
        try:
            with pdfplumber.open(archivo) as pdf:
                pagina = pdf.pages[0]
                tipo_decl, fecha_pres = extraer_datos_pie_pagina_tablas(pagina)
                
                per_txt = recuperar_periodo_regex(pagina)
                if per_txt == "0":
                    val_15 = extraer_valor_cuadrante(pagina, 15, es_total=True)
                    if val_15 != 0: per_txt = str(val_15)
                
                fecha_sort, nombre_per = obtener_nombre_periodo_sortable(per_txt, archivo.name)
                
                if nombre_per in nombres_vistos:
                    nombres_vistos[nombre_per] += 1
                    nombre_final = f"{nombre_per} ({nombres_vistos[nombre_per]})"
                else:
                    nombres_vistos[nombre_per] = 0
                    nombre_final = nombre_per
                
                fila = {
                    '_fecha_sort': fecha_sort,
                    'Periodo': nombre_final,
                    'TIPO DECLARACIÓN': tipo_decl,
                    'FECHA PAGO': fecha_pres
                }
                
                for cod in codigos_columna + codigos_totales:
                    es_total = (cod in codigos_totales)
                    valor = extraer_valor_cuadrante(pagina, cod, es_total=es_total)
                    nombre_columna = MAPA_ETIQUETAS.get(cod, f"CÓDIGO [{cod}]")
                    fila[nombre_columna] = valor
                
                lista_datos.append(fila)
        except Exception as e:
            st.error(f"Error {archivo.name}: {e}")
        progreso.progress((i+1)/len(archivos))
        
    progreso.empty()
    if not lista_datos: return None
    
    df = pd.DataFrame(lista_datos)
    if '_fecha_sort' in df.columns:
        df = df.sort_values('_fecha_sort').drop(columns=['_fecha_sort'])
        
    df = df.set_index('Periodo').transpose()
    df.index.name = "CONCEPTOS"
    return df

# ==========================================
# 4. INTERFAZ MEJORADA
# ==========================================

def main():
    st.title("📑 Auditoría Tributaria F-29")
    st.markdown("Sube tus archivos PDF mensuales. Utiliza los filtros laterales para analizar los datos.")

    with st.sidebar:
        st.header("1. Cargar Documentos")
        uploaded_files = st.file_uploader("Seleccionar PDFs", type="pdf", accept_multiple_files=True)
        boton_procesar = st.button("🚀 Procesar Archivos", type="primary")

    if "df_f29" not in st.session_state:
        st.session_state.df_f29 = None

    if uploaded_files and boton_procesar:
        with st.spinner("Procesando datos..."):
            st.session_state.df_f29 = procesar_pdfs_logica(uploaded_files)

    if st.session_state.df_f29 is not None:
        df_base = st.session_state.df_f29.copy()

        # FILTROS
        col_filt1, col_filt2, col_filt3 = st.columns(3)
        with col_filt1:
            todos_los_meses = df_base.columns.tolist()
            meses_sel = st.multiselect("📅 Filtrar Meses", todos_los_meses, default=[])
        
        with col_filt2:
            todos_los_conceptos = df_base.index.tolist()
            conceptos_sel = st.multiselect("🔢 Filtrar Conceptos", todos_los_conceptos, default=[])

        with col_filt3:
            st.write("🛠️ **Opciones de Vista**")
            usar_transpuesta = st.toggle("Transponer (Meses en filas)", value=False)

        if not meses_sel: meses_sel = todos_los_meses
        if not conceptos_sel: conceptos_sel = todos_los_conceptos

        df_filtrado = df_base.loc[conceptos_sel, meses_sel]

        # Lógica de Transposición
        if usar_transpuesta:
            df_final = df_filtrado.transpose()
        else:
            df_final = df_filtrado

        # --- VISUALIZACIÓN CON FORMATOS CONDICIONALES ---
        st.markdown("---")
        
        # 1. Creamos una copia string para mostrar (Display DataFrame)
        #    Esto es necesario para tener símbolos mezclados ($, %, ent) en la misma tabla
        df_display = df_final.copy()
        
        # Función que decide el formato fila por fila (si no está transpuesta)
        # o columna por columna (si está transpuesta)
        
        for idx in df_display.index: # Iteramos FILAS (Conceptos)
            nombre_concepto = str(idx)
            
            # Detectamos el código mirando el string, ej: "CANTIDAD... [503]"
            match = re.search(r'\[(\d+)\]', nombre_concepto)
            codigo = int(match.group(1)) if match else 0
            
            # Aplicamos formato a todas las columnas de esa fila
            for col in df_display.columns:
                val = df_display.at[idx, col]
                
                # Si no es un número (ej: Fechas o texto), lo dejamos igual
                if not isinstance(val, (int, float)) or isinstance(val, bool):
                    continue
                
                # LÓGICA DE FORMATO PEDIDA
                if codigo in CODIGOS_ENTERO:
                    # Formato Número (Ej: 1.200) sin signo peso
                    nuevo_val = f"{int(val):,}".replace(",", ".")
                
                elif codigo in CODIGOS_PORCENTAJE:
                    # Formato Porcentaje (Ej: 2%) con signo %
                    nuevo_val = f"{val}%" # Asumimos que viene como entero (ej: 2)
                
                else:
                    # Formato Pesos (Ej: $ 1.200) para el resto
                    # (Solo aplicamos $ si NO es fecha o texto, ya validado arriba)
                    nuevo_val = f"$ {int(val):,}".replace(",", ".")
                
                df_display.at[idx, col] = nuevo_val

        # Si el usuario transpone, la lógica anterior funciona igual porque modificamos
        # el DataFrame antes de mostrarlo, pero si está transpuesto, los conceptos
        # son columnas, así que debemos ajustar la lógica de iteración.
        
        # RE-HACEMOS LA LÓGICA DE FORMATO MÁS ROBUSTA PARA AMBOS CASOS:
        if usar_transpuesta:
            # Iteramos COLUMNAS (Conceptos)
            df_display = df_final.copy() # Reset
            for col in df_display.columns:
                nombre_concepto = str(col)
                match = re.search(r'\[(\d+)\]', nombre_concepto)
                codigo = int(match.group(1)) if match else 0
                
                # Aplicamos formato a toda la columna
                df_display[col] = df_display[col].apply(lambda x: 
                    f"{int(x):,}".replace(",", ".") if codigo in CODIGOS_ENTERO and isinstance(x, (int, float)) else
                    (f"{x}%" if codigo in CODIGOS_PORCENTAJE and isinstance(x, (int, float)) else
                    (f"$ {int(x):,}".replace(",", ".") if isinstance(x, (int, float)) else x))
                )
        else:
            # Iteramos FILAS (Conceptos) - Default
            df_display = df_final.copy() # Reset
            for idx in df_display.index:
                nombre_concepto = str(idx)
                match = re.search(r'\[(\d+)\]', nombre_concepto)
                codigo = int(match.group(1)) if match else 0
                
                # Aplicamos formato a toda la fila
                df_display.loc[idx] = df_display.loc[idx].apply(lambda x: 
                    f"{int(x):,}".replace(",", ".") if codigo in CODIGOS_ENTERO and isinstance(x, (int, float)) else
                    (f"{x}%" if codigo in CODIGOS_PORCENTAJE and isinstance(x, (int, float)) else
                    (f"$ {int(x):,}".replace(",", ".") if isinstance(x, (int, float)) else x))
                )

        # Aplicamos alineación a la izquierda
        styler = df_display.style.set_properties(**{'text-align': 'left'}) \
                             .set_table_styles([dict(selector='th', props=[('text-align', 'left')])])

        st.dataframe(styler, use_container_width=True, height=600)

        # DESCARGA (Usamos df_base numérico para que sirva en Excel)
        st.markdown("### 📥 Exportar")
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_base.to_excel(writer, sheet_name='F29_Datos_Crudos')
            df_display.to_excel(writer, sheet_name='Vista_Formateada')
            
        st.download_button(
            label="Descargar Excel",
            data=buffer.getvalue(),
            file_name="Analisis_F29.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )

if __name__ == "__main__":
    main()