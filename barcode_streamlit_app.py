#version 4 - Integrated with Google Drive (Solution A: Zero-Lag Queue + Bulk Sync)
import streamlit as st
import pandas as pd
import os
import shutil
import tempfile
import threading
from datetime import datetime
import time
import platform
import io
import drive_sync  # External module for Google Drive communication
import streamlit.components.v1 as components

# Import proper file locking libraries
try:
    import fcntl
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False

try:
    import msvcrt
    HAS_MSVCRT = True
except ImportError:
    HAS_MSVCRT = False

# Use portalocker if available (cross-platform)
try:
    import portalocker
    HAS_PORTALOCKER = True
except ImportError:
    HAS_PORTALOCKER = False

try:
    from filelock import FileLock as RealFileLock
    HAS_FILELOCK = True
except ImportError:
    HAS_FILELOCK = False

class ProcessSafeFileLock:
    """Cross-platform process-safe file lock implementation."""
    def __init__(self, path, timeout=10):
        self.path = os.path.abspath(path)
        self.timeout = timeout
        self.lock_file = None
        self.fd = None
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        
    def __enter__(self):
        if HAS_FILELOCK:
            self.lock_file = RealFileLock(self.path, timeout=self.timeout)
            self.lock_file.__enter__()
            return self
        if HAS_PORTALOCKER:
            self.fd = open(self.path, 'w')
            portalocker.lock(self.fd, portalocker.LOCK_EX, timeout=self.timeout)
            return self
        if HAS_FCNTL:
            self.fd = open(self.path, 'w')
            start_time = time.time()
            while True:
                try:
                    fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return self
                except (IOError, OSError):
                    if time.time() - start_time >= self.timeout:
                        raise TimeoutError(f"Could not acquire lock on {self.path} within {self.timeout}s }}")
                    time.sleep(0.1)
        if HAS_MSVCRT:
            self.fd = open(self.path, 'w')
            start_time = time.time()
            while True:
                try:
                    msvcrt.locking(self.fd.fileno(), msvcrt.LK_LOCK, 1)
                    return self
                except (IOError, OSError):
                    if time.time() - start_time >= self.timeout:
                        raise TimeoutError(f"Could not acquire lock on {self.path} within {self.timeout}s }}")
                    time.sleep(0.1)
        start_time = time.time()
        while True:
            try:
                if not os.path.exists(self.path):
                    with open(self.path, 'w') as f:
                        f.write(str(os.getpid()))
                    return self
                if time.time() - start_time >= self.timeout:
                    raise TimeoutError(f"Could not acquire lock on {self.path} within {self.timeout}s")
                time.sleep(0.1)
            except Exception:
                if time.time() - start_time >= self.timeout:
                    raise
                time.sleep(0.1)
                
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.lock_file:
            self.lock_file.__exit__(exc_type, exc_val, exc_tb)
        elif self.fd:
            try:
                if HAS_PORTALOCKER:
                    portalocker.unlock(self.fd)
                elif HAS_FCNTL:
                    fcntl.flock(self.fd, fcntl.LOCK_UN)
                elif HAS_MSVCRT:
                    msvcrt.locking(self.fd.fileno(), msvcrt.LK_UNLCK, 1)
                self.fd.close()
            except Exception:
                pass
        else:
            try:
                if os.path.exists(self.path):
                    os.remove(self.path)
            except Exception:
                pass
        return False

FileLock = ProcessSafeFileLock

# Configuration
INVENTORY_PATH = "inventory.csv"
LOCK_PATH = os.path.abspath(INVENTORY_PATH) + ".lock"
BACKUP_PATH = "inventory.csv.bak"
SESSION_BACKUP_DIR = "session_backups"
SESSION_BACKUP_LOCK = os.path.abspath("session_backup.lock")

st.set_page_config(page_title="Barcode Scanner Inventory", page_icon="📦", layout="wide", initial_sidebar_state="expanded")

class SessionCounter:
    def __init__(self):
        if 'session_total' not in st.session_state:
            st.session_state.session_total = 0
        if 'scanned_items' not in st.session_state:
            st.session_state.scanned_items = []
        if 'session_start_time' not in st.session_state:
            st.session_state.session_start_time = datetime.now()
        if 'session_backup_path' not in st.session_state:
            os.makedirs(SESSION_BACKUP_DIR, exist_ok=True)
            stamp = st.session_state.session_start_time.strftime("%Y%m%d_%H%M%S")
            st.session_state.session_backup_path = os.path.join(SESSION_BACKUP_DIR, f"session_{stamp}.csv")

    def add_item(self, barcode, product_name, old_qty, new_qty, action='scan'):
        st.session_state.session_total += 1
        st.session_state.scanned_items.append({
            'barcode': barcode,
            'product_name': product_name,
            'old_qty': old_qty,
            'new_qty': new_qty,
            'action': action,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        self._save_session_backup()

    def _save_session_backup(self):
        if not st.session_state.scanned_items:
            return
        try:
            df = pd.DataFrame(st.session_state.scanned_items)
            path = st.session_state.session_backup_path
            dir_name = os.path.dirname(os.path.abspath(path)) or "."
            with FileLock(SESSION_BACKUP_LOCK, timeout=10):
                fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".csv.tmp")
                os.close(fd)
                df.to_csv(tmp_path, index=False, encoding='utf-8-sig')
                os.replace(tmp_path, path)
        except Exception as e:
            pass

    def get_session_total(self): return st.session_state.session_total
    def get_session_duration(self): return datetime.now() - st.session_state.session_start_time
    def get_backup_path(self): return st.session_state.get('session_backup_path')
    def reset_session(self):
        st.session_state.session_total = 0
        st.session_state.scanned_items = []
        st.session_state.session_start_time = datetime.now()
        os.makedirs(SESSION_BACKUP_DIR, exist_ok=True)
        stamp = st.session_state.session_start_time.strftime("%Y%m%d_%H%M%S")
        st.session_state.session_backup_path = os.path.join(SESSION_BACKUP_DIR, f"session_{stamp}.csv")

def standardize_columns(df):
    canonical_mapping = {'barcode': 'Barcode', 'name': 'Name', 'qty': 'Qty', 'quantity': 'Qty', 'qtynew': 'Qty_new', 'newqty': 'Qty_new', 'qty_new': 'Qty_new', 'new_quantity': 'Qty_new'}
    new_columns = []
    for col in df.columns:
        cleaned = str(col).lower().replace(' ', '').replace('_', '')
        new_columns.append(canonical_mapping.get(cleaned, str(col)))
    df.columns = new_columns
    return df

def validate_and_clean_barcodes(df):
    if 'Barcode' not in df.columns: return df
    df['Barcode'] = df['Barcode'].astype(str).str.strip()
    df = df[(df['Barcode'] != '') & (df['Barcode'] != 'nan')]
    df = df.drop_duplicates(subset=['Barcode'], keep='last')
    return df

def load_inventory_df(force_reload=False):
    """Load inventory from Google Drive to session cache."""
    cached_df = st.session_state.get('inventory_df')
    if (not force_reload) and cached_df is not None:
        return cached_df.copy()
    
    # Fetch from Google Drive
    csv_content = drive_sync.fetch_inventory_from_drive()
    if not csv_content:
        st.error("Failed to load inventory from Google Drive.")
        return None
    
    try:
        # Parse the downloaded text directly into pandas
        df = pd.read_csv(io.StringIO(csv_content), dtype={'Barcode': str})
        df = standardize_columns(df)
        df = validate_and_clean_barcodes(df)
    except Exception as e:
        st.error(f"Error parsing Google Drive CSV: {e}")
        return None
    
    st.session_state['inventory_df'] = df
    st.session_state['unsynced_changes'] = False # Reset sync flag
    return df.copy()

def save_inventory_data(df):
    """Saves to session state and writes local backup."""
    df = df.copy()
    if 'Barcode' in df.columns:
        df = validate_and_clean_barcodes(df)
        
    st.session_state['inventory_df'] = df
    st.session_state['unsynced_changes'] = True
    
    # Save a local cache silently
    try:
        with FileLock(LOCK_PATH, timeout=5):
            df.to_csv(INVENTORY_PATH, index=False, encoding='utf-8-sig')
    except Exception:
        pass
    return True

def scan_barcode(qty_col, qty_new_col, name_col, barcode_input, session_counter, action='scan'):
    """Zero-Lag scan tracking in local session state."""
    try:
        df = load_inventory_df()
        if df is None or df.empty:
            return "not_found"
            
        barcode_input_str = str(barcode_input).strip()
        df['Barcode'] = df['Barcode'].astype(str).str.strip()
        
        matching_rows = df[df['Barcode'] == barcode_input_str]
        if matching_rows.empty:
            return "not_found"
            
        matching_idx = matching_rows.index[0]
        
        if qty_new_col not in df.columns:
            df[qty_new_col] = 0
            
        current_value = df.loc[matching_idx, qty_new_col]
        try:
            new_value = int(float(current_value)) + 1 if pd.notna(current_value) else 1
        except (ValueError, TypeError):
            new_value = 1
            
        df.loc[matching_idx, qty_new_col] = new_value
        updated_product = df.loc[matching_idx].copy()
        
        save_inventory_data(df)
            
        session_counter.add_item(
            barcode=updated_product['Barcode'],
            product_name=updated_product.get(name_col, ""),
            old_qty=updated_product.get(qty_col, 0),
            new_qty=new_value,
            action=action
        )
        return updated_product, new_value
    except Exception as e:
        st.error(f"Error updating inventory: {e}")
        return None

def single_scan_mode(session_counter):
    st.header("📱 Single Scan Mode")
    df = load_inventory_df()
    if df is None: return

    with st.form("single_scan_form", clear_on_submit=True):
        col1, col2 = st.columns([3, 1])
        with col1:
            barcode_input = st.text_input("Scan or enter barcode:", placeholder="Scan or type barcode...", key="barcode_scanner_input")
            components.html(
                """<script>
                    const inputs = window.parent.document.querySelectorAll('input');
                    for (let i = 0; i < inputs.length; i++) {
                        if (inputs[i].getAttribute('aria-label') === 'Scan or enter barcode:') {
                            inputs[i].focus(); break;
                        }
                    }
                </script>""", height=0, width=0)
        with col2:
            st.write("")
            submitted = st.form_submit_button("Scan Item", type="primary", use_container_width=True)

    if submitted:
        barcode_input = str(barcode_input or "").strip()
        if not barcode_input:
            st.warning("Please enter or scan a barcode.")
            return
        
        result = scan_barcode('Qty', 'Qty_new', 'Name', barcode_input, session_counter)
        if result == "not_found":
            st.error(f"Barcode '{barcode_input}' not found in database!")
        elif result is not None:
            updated_product, new_value = result
            st.success("✅ Item scanned successfully!")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Product", updated_product.get('Name', ""))
            col2.metric("Barcode", updated_product['Barcode'])
            col3.metric("Old Scanned Qty", int(updated_product.get('Qty_new', 0)))
            col4.metric("New Scanned Qty", int(new_value))

def continuous_scan_mode(session_counter):
    st.header("🔄 Continuous Scan Mode")
    df = load_inventory_df()
    if df is None: return
    
    if 'continuous_scan_active' not in st.session_state:
        st.session_state.continuous_scan_active = False

    col1, col2 = st.columns([1, 2])
    with col1:
        if st.button("🎯 Start Continuous Scan", type="primary", use_container_width=True):
            st.session_state.continuous_scan_active = True
        if st.button("🛑 Stop Continuous Scan", use_container_width=True):
            st.session_state.continuous_scan_active = False

    if st.session_state.continuous_scan_active:
        st.info("💡 Scan barcodes in the input field below.")
        with st.form("continuous_scan_form", clear_on_submit=True):
            barcode_input = st.text_input("Scan barcode:", placeholder="Scan barcode...")
            submitted = st.form_submit_button("Add Scan", use_container_width=True)
            
        if submitted:
            barcode_input = str(barcode_input or "").strip()
            if barcode_input:
                result = scan_barcode('Qty', 'Qty_new', 'Name', barcode_input, session_counter)
                if result == "not_found":
                    st.error(f"Barcode '{barcode_input}' not found!")
                elif result is not None:
                    updated_product, new_value = result
                    st.success(f"✅ Scanned: {updated_product.get('Name', '')} - New Qty: {new_value}")

def show_session_summary(session_counter):
    st.header("📊 Session Summary")
    col1, col2, col3 = st.columns(3)
    with col1: st.metric("Total Items Scanned", session_counter.get_session_total())
    with col2:
        duration = session_counter.get_session_duration()
        st.metric("Session Duration", f"{int(duration.total_seconds()) // 3600}h {(int(duration.total_seconds()) % 3600) // 60}m")
    with col3:
        if st.button("🔄 Reset Session", use_container_width=True):
            session_counter.reset_session()
            st.rerun()

    if st.session_state.scanned_items:
        summary_df = pd.DataFrame(st.session_state.scanned_items)
        st.dataframe(summary_df, use_container_width=True, hide_index=True)
        st.download_button(label="📥 Download Session CSV", data=summary_df.to_csv(index=False, encoding='utf-8-sig'), file_name=f"scan_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", mime="text/csv")
    else:
        st.info("No items scanned in this session yet.")

def inventory_overview():
    st.header("📦 Inventory Overview")
    df = load_inventory_df()
    if df is None: return

    qty_new_numeric = pd.to_numeric(df['Qty_new'], errors='coerce').fillna(0)
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Products", len(df))
    col2.metric("Total Items Scanned", int(qty_new_numeric.sum()))
    col3.metric("Unique Items Scanned", int((qty_new_numeric > 0).sum()))

    scanned_items = df[qty_new_numeric > 0]
    if not scanned_items.empty:
        st.subheader("✅ Scanned Items")
        display_df = scanned_items[['Barcode', 'Name', 'Qty_new']].copy()
        display_df.columns = ['Barcode', 'Product Name', 'Scanned Quantity']
        st.dataframe(display_df, use_container_width=True, hide_index=True)

    st.subheader("🔍 Full Inventory")
    search_term = st.text_input("Search products:")
    if search_term:
        mask = df['Name'].astype(str).str.contains(search_term, case=False, na=False) | df['Barcode'].astype(str).str.contains(search_term, case=False, na=False)
        df = df[mask]
    st.dataframe(df[['Barcode', 'Name', 'Qty', 'Qty_new']], use_container_width=True, hide_index=True, height=400)

def file_management(session_counter):
    st.header("⚙️ File Management")
    st.info("Sync happens automatically via the sidebar, but you can download local backups here.")
    df = load_inventory_df()
    if df is not None:
        csv = df.to_csv(index=False, encoding='utf-8-sig')
        st.download_button("📥 Download inventory.csv Backup", data=csv, file_name="inventory.csv", mime="text/csv")

def update_scanned_item_form(session_counter):
    st.header("✏️ Update Scanned Item Quantity")
    df = load_inventory_df()
    if df is None: return

    session_barcodes = [str(item['barcode']).strip() for item in st.session_state.get('scanned_items', [])]
    combined = list(dict.fromkeys(session_barcodes + df['Barcode'].astype(str).str.strip().unique().tolist()))

    col1, col2 = st.columns([2, 1])
    with col1: barcode_choice = st.selectbox("Select barcode:", options=["-- Enter manually --"] + combined)
    with col2:
        manual_barcode = st.text_input("Or enter barcode:")
        components.html("""<script>
            const inputs = window.parent.document.querySelectorAll('input');
            for (let i=0; i<inputs.length; i++) { if(inputs[i].getAttribute('aria-label') === 'Or enter barcode:') { inputs[i].focus(); break; } }
        </script>""", height=0, width=0)

    chosen_barcode = str(barcode_choice).strip() if barcode_choice != "-- Enter manually --" else str(manual_barcode).strip()

    if chosen_barcode:
        matching = df[df['Barcode'].astype(str).str.strip() == chosen_barcode]
        if matching.empty:
            st.error(f"Barcode '{chosen_barcode}' not found.")
        else:
            product = matching.iloc[0]
            st.markdown(f"**Product:** {product.get('Name', '')}")
            current_scanned = int(float(product.get('Qty_new', 0))) if pd.notna(product.get('Qty_new', 0)) else 0
            new_scanned = st.number_input("Set new scanned quantity:", min_value=0, value=current_scanned)
            
            if st.button("Update Quantity", use_container_width=True):
                df.loc[matching.index[0], 'Qty_new'] = new_scanned
                save_inventory_data(df)
                st.success(f"Updated {chosen_barcode} to {new_scanned}")
                st.rerun()

def main():
    session_counter = SessionCounter()
    
    with st.sidebar:
        st.title("📦 Barcode Scanner")
        st.markdown("---")
        
        # --- NEW BULK SYNC BUTTON ---
        st.subheader("☁️ Cloud Sync")
        if st.session_state.get('unsynced_changes', False):
            st.warning("⚠️ Unsynced Scans Waiting!")
            
        if st.button("Sync to Google Drive", use_container_width=True, type="primary"):
            with st.spinner("Syncing..."):
                current_df = st.session_state.get('inventory_df')
                if current_df is not None:
                    csv_string = current_df.to_csv(index=False, encoding='utf-8-sig')
                    if drive_sync.push_inventory_to_drive(csv_string):
                        st.session_state['unsynced_changes'] = False
                        st.success("✅ Synced!")
                    else:
                        st.error("❌ Sync Failed")
        st.markdown("---")
        
        st.metric("Session Total", session_counter.get_session_total())
        st.markdown("---")
        st.subheader("Navigation")
        page = st.radio("Go to:", ["Single Scan", "Continuous Scan", "Session Summary", "Inventory Overview", "Update Scanned Item", "File Management"], label_visibility="collapsed")
        
        if st.button("🔄 Reload from Drive", use_container_width=True):
            load_inventory_df(force_reload=True)
            st.rerun()
            
        st.markdown("*Developed with AmR ELSaadAnY*")

    if page == "Single Scan": single_scan_mode(session_counter)
    elif page == "Continuous Scan": continuous_scan_mode(session_counter)
    elif page == "Session Summary": show_session_summary(session_counter)
    elif page == "Inventory Overview": inventory_overview()
    elif page == "Update Scanned Item": update_scanned_item_form(session_counter)
    elif page == "File Management": file_management(session_counter)

if __name__ == "__main__":
    main()