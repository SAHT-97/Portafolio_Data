import streamlit as st
import pdfplumber
import pandas as pd
import io
import re

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Extractor F29 - Final", page_icon="📊", layout="wide")

st.title("Centralización F-29")
st.markdown("Sube tus archivos PDF.")

# --- UTILIDADES ---

def limpiar_numero(valor_texto):
    """Limpia y convierte texto numérico a entero"""
    try:
        if not valor_texto: return 0
        val_str = str(valor_texto).replace('.', '').replace(' ', '').strip()
        if not val_str or not val_str.replace('-','').isdigit():
            return 0
        return int(val_str)
    except:
        return 0

def obtener_nombre_periodo(texto_periodo):
    """Convierte '202305' -> 'Mayo 2023'"""
    try:
        s_valor = str(texto_periodo).strip()
        match = re.search(r'(20\d{2})(0[1-9]|1[0-2])', s_valor)
        if match:
            anio = match.group(1)
            mes = match.group(2)
            mapa_meses = {
                "01": "Enero", "02": "Febrero", "03": "Marzo", "04": "Abril",
                "05": "Mayo", "06": "Junio", "07": "Julio", "08": "Agosto",
                "09": "Septiembre", "10": "Octubre", "11": "Noviembre", "12": "Diciembre"
            }
            return f"{mapa_meses.get(mes, 'Mes')} {anio}"
        return s_valor
    except:
        return "Periodo Desconocido"

# --- LÓGICA DE EXTRACCIÓN HÍBRIDA ---

def extraer_valor_flexible(pagina, codigo_buscado, estrategia="columna"):
    """
    Busca valores usando dos estrategias:
    1. 'columna': Divide la página en dos. Ideal para sección media.
    2. 'fila_completa': Escanea toda la línea a la derecha. Ideal para totales (91, 94, 795).
    """
    words = pagina.extract_words()
    ancho_pagina = pagina.width
    mitad_pagina = ancho_pagina / 2
    
    # 1. Ubicar el código
    codigo_obj = None
    for word in words:
        if word['text'] == str(codigo_buscado):
            codigo_obj = word
            break
            
    if not codigo_obj:
        return 0

    y_mid = (codigo_obj['top'] + codigo_obj['bottom']) / 2
    x_fin_codigo = codigo_obj['x1']
    esta_a_la_izquierda = codigo_obj['x0'] < mitad_pagina
    
    # 2. Filtrar candidatos (Números en la misma línea)
    candidatos = []
    
    # Tolerancia vertical un poco más alta para los totales que a veces tienen cajas grandes
    tolerancia = 6 if estrategia == "columna" else 8
    
    for word in words:
        if word == codigo_obj: continue
        
        # Filtro Vertical
        word_mid = (word['top'] + word['bottom']) / 2
        if abs(word_mid - y_mid) > tolerancia:
            continue
            
        # Filtro Horizontal Básico: Debe estar a la derecha del código
        if word['x0'] <= x_fin_codigo:
            continue
            
        # --- AQUI ESTÁ LA MAGIA ---
        if estrategia == "columna":
            # APLICAR MUROS: Si es columna, no cruzar la mitad de la página
            if esta_a_la_izquierda:
                if word['x1'] > (mitad_pagina + 15): continue
            else:
                if word['x0'] < (mitad_pagina - 15): continue
        
        elif estrategia == "fila_completa":
            # SIN MUROS: Permitir buscar hasta el borde derecho de la hoja
            pass
            
        candidatos.append(word)
    
    if not candidatos:
        return 0

    # 3. Selección del Valor
    # Ordenamos de izquierda a derecha
    candidatos.sort(key=lambda w: w['x0'])
    
    # Para la sección inferior (totales), el valor suele estar en una columna específica a la derecha.
    # Pero a veces hay símbolos (+, -) al final. 
    # Buscamos el último que sea un número válido o el primero válido desde la derecha.
    for word in reversed(candidatos):
        texto = word['text']
        val = limpiar_numero(texto)
        if val > 0 or texto.strip() == '0':
            return val
            
    return 0

def extraer_periodo(pagina):
    """Busca el periodo (Cod 15) en la cabecera"""
    # Usamos estrategia 'columna' porque el 15 está arriba a la derecha usualmente
    val = extraer_valor_flexible(pagina, "15", estrategia="fila_completa") 
    if val > 200000: return obtener_nombre_periodo(val)
    
    # Fallback: Regex en texto
    try:
        texto = pagina.crop((0, 0, pagina.width, 250)).extract_text()
        match = re.search(r'\b(20[2-3]\d)(0[1-9]|1[0-2])\b', texto)
        if match: return obtener_nombre_periodo(match.group(0))
    except:
        pass
    return "Sin Periodo"

def procesar_pdfs(archivos):
    # Definición de estrategias por código
    codigos_columna = [538, 537, 62, 49, 48, 151, 155, 598]
    codigos_totales = [91, 92, 93, 94, 795] # Agregado 795
    
    datos = []
    progreso = st.progress(0)
    
    for i, archivo in enumerate(archivos):
        try:
            with pdfplumber.open(archivo) as pdf:
                pagina = pdf.pages[0]
                
                # Periodo
                per = extraer_periodo(pagina)
                nombre_fila = per if per != "Sin Periodo" else archivo.name
                
                fila = {'Archivo': nombre_fila}
                
                # Extraer Sección Central (Estrategia Columnas)
                for cod in codigos_columna:
                    fila[cod] = extraer_valor_flexible(pagina, cod, estrategia="columna")
                    
                # Extraer Sección Inferior (Estrategia Fila Completa)
                for cod in codigos_totales:
                    fila[cod] = extraer_valor_flexible(pagina, cod, estrategia="fila_completa")
                
                datos.append(fila)
                
        except Exception as e:
            st.error(f"Error {archivo.name}: {e}")
        progreso.progress((i+1)/len(archivos))
        
    progreso.empty()
    
    if not datos: return None, None
    
    df = pd.DataFrame(datos)
    
    # Rellenar y Ordenar
    all_codes = codigos_columna + codigos_totales
    for c in all_codes:
        if c not in df.columns: df[c] = 0
            
    df1 = df[['Archivo'] + codigos_columna].copy()
    df2 = df[['Archivo'] + codigos_totales].copy()
    
    return df1, df2

def df_to_excel(df1, df2):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df1.to_excel(writer, sheet_name='Detalle_Impuestos', index=False)
        df2.to_excel(writer, sheet_name='Totales_Pago', startrow=0, index=False)
    return output.getvalue()

# --- INTERFAZ ---
st.markdown("### 📁 Cargar PDF Formulario 29")
st.info("Arrastra los archivos individuales o la carpeta completa")

uploaded = st.file_uploader("Subir archivos", type="pdf", accept_multiple_files=True)

if uploaded and st.button("🚀 Extraer Datos", type="primary"):
    df_central, df_totales = procesar_pdfs(uploaded)
    
    if df_central is not None:
        st.success("✅ Extracción completada")
        
        # Mostrar Tablas
        st.markdown("#### 1️⃣ Codigos del Detalle Impuestos ")
        st.dataframe(df_central.style.format({c: "{:,.0f}".format for c in df_central.columns if c!='Archivo'}))
        
        st.markdown("#### 2️⃣ Codigos de los Totales a Pagar ")
        st.dataframe(df_totales.style.format({c: "{:,.0f}".format for c in df_totales.columns if c!='Archivo'}))
        
        # Descarga
        st.download_button(
            "📥 Descargar Excel Reporte",
            data=df_to_excel(df_central, df_totales),
            file_name="Reporte_F29_Completo.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )