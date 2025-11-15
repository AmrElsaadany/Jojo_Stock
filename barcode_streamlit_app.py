# barcode_streamlit_app.py
import streamlit as st
import pandas as pd
import os
from datetime import datetime
import time

# Set page configuration
st.set_page_config(
    page_title="Barcode Scanner Inventory",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)

class SessionCounter:
    """Class to track session statistics"""
    def __init__(self):
        if 'session_total' not in st.session_state:
            st.session_state.session_total = 0
        if 'scanned_items' not in st.session_state:
            st.session_state.scanned_items = []
        if 'session_start_time' not in st.session_state:
            st.session_state.session_start_time = datetime.now()
    
    def add_item(self, barcode, product_name, old_qty, new_qty):
        """Add an item to session counter"""
        st.session_state.session_total += 1
        st.session_state.scanned_items.append({
            'barcode': barcode,
            'product_name': product_name,
            'old_qty': old_qty,
            'new_qty': new_qty,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
    
    def get_session_total(self):
        """Get total items scanned in this session"""
        return st.session_state.session_total
    
    def get_session_duration(self):
        """Get session duration"""
        return datetime.now() - st.session_state.session_start_time
    
    def reset_session(self):
        """Reset the session"""
        st.session_state.session_total = 0
        st.session_state.scanned_items = []
        st.session_state.session_start_time = datetime.now()

def read_csv_with_encoding(file_path):
    """Read CSV file with Arabic (Windows-1256) encoding"""
    try:
        # Try Windows-1256 (Arabic) encoding first
        return pd.read_csv(file_path, encoding='windows-1256')
    except UnicodeDecodeError:
        try:
            # Try UTF-8 as fallback
            return pd.read_csv(file_path, encoding='utf-8')
        except:
            # Try other common encodings
            encodings = ['cp1256', 'iso-8859-6', 'latin1', 'cp1252']
            for enc in encodings:
                try:
                    st.warning(f"Trying encoding: {enc}")
                    return pd.read_csv(file_path, encoding=enc)
                except:
                    continue
            raise Exception("Could not read the CSV file with any supported encoding")

def normalize_column_names(df):
    """Normalize column names to handle different cases and spaces"""
    column_mapping = {}
    
    for col in df.columns:
        normalized = col.lower().replace(' ', '').replace('_', '')
        column_mapping[normalized] = col
    
    return column_mapping

def update_inventory_data():
    """Load and return inventory data"""
    file_path = "inventory.csv"
    
    if not os.path.exists(file_path):
        st.error(f"File '{file_path}' not found!")
        return None
    
    try:
        df = read_csv_with_encoding(file_path)
        return df
    except Exception as e:
        st.error(f"Error reading file: {e}")
        return None

def save_inventory_data(df):
    """Save inventory data back to CSV"""
    try:
        df.to_csv("inventory.csv", index=False, encoding='windows-1256')
        return True
    except Exception as e:
        st.error(f"Error saving file: {e}")
        return False

def single_scan_mode(session_counter):
    """Single barcode scan mode"""
    st.header("📱 Single Scan Mode")
    
    df = update_inventory_data()
    if df is None:
        return
    
    # Normalize column names
    column_mapping = normalize_column_names(df)
    
    # Check required columns
    required_columns = ['barcode', 'name', 'qty', 'qtynew']
    missing_columns = [col for col in required_columns if col not in column_mapping]
    
    if missing_columns:
        st.error(f"Missing columns: {missing_columns}")
        st.info("Please ensure your CSV has columns for barcode, name, quantity, and new quantity")
        return
    
    # Get actual column names
    barcode_col = column_mapping['barcode']
    name_col = column_mapping['name']
    qty_col = column_mapping['qty']
    qty_new_col = column_mapping['qtynew']
    
    # Barcode input
    col1, col2 = st.columns([2, 1])
    with col1:
        barcode_input = st.text_input("Scan or enter barcode:", key="single_scan_input")
    with col2:
        scan_button = st.button("Scan Item", type="primary", use_container_width=True)
    
    if scan_button and barcode_input:
        # Convert barcode column to string for comparison
        df[barcode_col] = df[barcode_col].astype(str)
        
        # Find matching barcode
        matching_rows = df[df[barcode_col] == barcode_input]
        
        if matching_rows.empty:
            st.error(f"Barcode '{barcode_input}' not found in database!")
            
            # Show available barcodes
            with st.expander("Show available barcodes"):
                st.write("First 20 barcodes:")
                st.code(", ".join(df[barcode_col].head(20).astype(str).tolist()))
        else:
            # Update quantity
            current_value = df.loc[df[barcode_col] == barcode_input, qty_new_col].iloc[0]
            if pd.isna(current_value):
                new_value = 1
            else:
                new_value = current_value + 1
            
            df.loc[df[barcode_col] == barcode_input, qty_new_col] = new_value
            
            # Get updated product info
            updated_product = df[df[barcode_col] == barcode_input].iloc[0]
            
            # Add to session counter
            session_counter.add_item(
                barcode=updated_product[barcode_col],
                product_name=updated_product[name_col],
                old_qty=updated_product[qty_col],
                new_qty=new_value
            )
            
            # Save changes
            if save_inventory_data(df):
                # Success message
                st.success("✅ Item scanned successfully!")
                
                # Display product info
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Product", updated_product[name_col])
                with col2:
                    st.metric("Barcode", updated_product[barcode_col])
                with col3:
                    st.metric("Old Quantity", int(updated_product[qty_col]))
                with col4:
                    st.metric("New Quantity", int(new_value))
                
                # Auto-clear after successful scan
                time.sleep(1)
                st.rerun()

def continuous_scan_mode(session_counter):
    """Continuous scan mode"""
    st.header("🔄 Continuous Scan Mode")
    
    df = update_inventory_data()
    if df is None:
        return
    
    # Normalize column names
    column_mapping = normalize_column_names(df)
    barcode_col = column_mapping['barcode']
    name_col = column_mapping['name']
    qty_col = column_mapping['qty']
    qty_new_col = column_mapping['qtynew']
    
    # Initialize continuous scan state
    if 'continuous_scan_active' not in st.session_state:
        st.session_state.continuous_scan_active = False
    if 'current_scan_input' not in st.session_state:
        st.session_state.current_scan_input = ""
    
    col1, col2 = st.columns([1, 2])
    with col1:
        if st.button("🎯 Start Continuous Scan", type="primary", use_container_width=True):
            st.session_state.continuous_scan_active = True
            st.success("Continuous scan mode activated! Scan barcodes below.")
        
        if st.button("🛑 Stop Continuous Scan", use_container_width=True):
            st.session_state.continuous_scan_active = False
            st.info("Continuous scan mode stopped.")
    
    if st.session_state.continuous_scan_active:
        st.info("💡 Scan barcodes in the input field below. Press Enter after each scan.")
        
        # Barcode input for continuous mode
        barcode_input = st.text_input(
            "Scan barcode (press Enter after each scan):",
            key="continuous_scan_input",
            placeholder="Scan barcode and press Enter..."
        )
        
        if barcode_input and barcode_input != st.session_state.current_scan_input:
            st.session_state.current_scan_input = barcode_input
            
            # Convert barcode column to string
            df[barcode_col] = df[barcode_col].astype(str)
            
            # Find matching barcode
            matching_rows = df[df[barcode_col] == barcode_input]
            
            if matching_rows.empty:
                st.error(f"Barcode '{barcode_input}' not found!")
            else:
                # Update quantity
                current_value = df.loc[df[barcode_col] == barcode_input, qty_new_col].iloc[0]
                if pd.isna(current_value):
                    new_value = 1
                else:
                    new_value = current_value + 1
                
                df.loc[df[barcode_col] == barcode_input, qty_new_col] = new_value
                
                # Get updated product info
                updated_product = df[df[barcode_col] == barcode_input].iloc[0]
                
                # Add to session counter
                session_counter.add_item(
                    barcode=updated_product[barcode_col],
                    product_name=updated_product[name_col],
                    old_qty=updated_product[qty_col],
                    new_qty=new_value
                )
                
                # Save changes
                if save_inventory_data(df):
                    st.success(f"✅ Scanned: {updated_product[name_col]} - New Qty: {new_value}")
                    
                    # Auto-clear and rerun
                    time.sleep(0.5)
                    st.rerun()

def show_session_summary(session_counter):
    """Display session summary"""
    st.header("📊 Session Summary")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Items Scanned", session_counter.get_session_total())
    with col2:
        duration = session_counter.get_session_duration()
        st.metric("Session Duration", f"{duration.seconds // 3600}h {(duration.seconds % 3600) // 60}m")
    with col3:
        if st.button("🔄 Reset Session", use_container_width=True):
            session_counter.reset_session()
            st.success("Session reset successfully!")
            time.sleep(1)
            st.rerun()
    
    # Display scanned items table
    if st.session_state.scanned_items:
        st.subheader("📋 Scanned Items")
        summary_df = pd.DataFrame(st.session_state.scanned_items)
        st.dataframe(
            summary_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "timestamp": "Time",
                "barcode": "Barcode",
                "product_name": "Product Name",
                "old_qty": "Old Qty",
                "new_qty": "New Qty"
            }
        )
        
        # Export option
        if st.button("📥 Export Session Data"):
            csv = summary_df.to_csv(index=False, encoding='utf-8')
            st.download_button(
                label="Download CSV",
                data=csv,
                file_name=f"scan_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
    else:
        st.info("No items scanned in this session yet.")

def inventory_overview():
    """Display inventory overview"""
    st.header("📦 Inventory Overview")
    
    df = update_inventory_data()
    if df is None:
        return
    
    # Normalize column names
    column_mapping = normalize_column_names(df)
    
    # Check if we have the required columns
    if 'qtynew' in column_mapping:
        qty_new_col = column_mapping['qtynew']
        name_col = column_mapping['name']
        barcode_col = column_mapping['barcode']
        
        # Display statistics
        total_scanned = df[qty_new_col].sum() if not df[qty_new_col].isna().all() else 0
        unique_items_scanned = df[df[qty_new_col] > 0].shape[0] if not df[qty_new_col].isna().all() else 0
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Products", len(df))
        with col2:
            st.metric("Total Items Scanned", int(total_scanned))
        with col3:
            st.metric("Unique Items Scanned", unique_items_scanned)
        
        # Show items that have been scanned
        scanned_items = df[df[qty_new_col] > 0] if not df[qty_new_col].isna().all() else pd.DataFrame()
        if not scanned_items.empty:
            st.subheader("✅ Scanned Items in Inventory")
            display_df = scanned_items[[barcode_col, name_col, qty_new_col]].copy()
            display_df.columns = ['Barcode', 'Product Name', 'Scanned Quantity']
            st.dataframe(display_df, use_container_width=True, hide_index=True)
        
        # Show all inventory with search
        st.subheader("🔍 Full Inventory")
        search_term = st.text_input("Search products:", placeholder="Enter product name or barcode...")
        
        display_full_df = df.copy()
        if search_term:
            mask = (
                display_full_df[name_col].astype(str).str.contains(search_term, case=False, na=False) |
                display_full_df[barcode_col].astype(str).str.contains(search_term, case=False, na=False)
            )
            display_full_df = display_full_df[mask]
        
        # Select columns to display
        display_columns = [barcode_col, name_col]
        if 'qty' in column_mapping:
            display_columns.append(column_mapping['qty'])
        if 'qtynew' in column_mapping:
            display_columns.append(column_mapping['qtynew'])
        
        st.dataframe(
            display_full_df[display_columns],
            use_container_width=True,
            hide_index=True,
            height=400
        )

def file_management():
    """File management section"""
    st.header("⚙️ File Management")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Fix File Encoding")
        if st.button("🔧 Fix Encoding to Windows-1256", use_container_width=True):
            file_path = "inventory.csv"
            if os.path.exists(file_path):
                try:
                    df = pd.read_csv(file_path)
                    df.to_csv(file_path, index=False, encoding='windows-1256')
                    st.success("File encoding fixed to Windows-1256 (Arabic)")
                except Exception as e:
                    st.error(f"Error fixing encoding: {e}")
            else:
                st.error("inventory.csv not found!")
    
    with col2:
        st.subheader("Create Sample File")
        if st.button("📝 Create Sample Inventory", use_container_width=True):
            sample_data = {
                'Barcode': ['123456789', '987654321', '555555555', '111111111', '39200'],
                'Name': ['منتج أ', 'منتج ب', 'منتج ج', 'منتج د', 'منتج اختبار'],
                'Qty': [10, 5, 20, 15, 8],
                'Qty_new': [0, 0, 0, 0, 0]
            }
            
            df = pd.DataFrame(sample_data)
            df.to_csv('inventory.csv', index=False, encoding='windows-1256')
            st.success("Sample inventory.csv created successfully!")
            st.info("Sample barcodes: 123456789, 987654321, 555555555, 111111111, 39200")

def main():
    """Main application"""
    # Initialize session counter
    session_counter = SessionCounter()
    
    # Sidebar
    with st.sidebar:
        st.title("📦 Barcode Scanner")
        st.markdown("---")
        
        # Session info
        st.metric("Session Total", session_counter.get_session_total())
        st.markdown("---")
        
        # Navigation
        st.subheader("Navigation")
        page = st.radio(
            "Go to:",
            ["Single Scan", "Continuous Scan", "Session Summary", "Inventory Overview", "File Management"],
            label_visibility="collapsed"
        )
        
        st.markdown("---")
        st.markdown("### Quick Actions")
        if st.button("🔄 Reset Current Session", use_container_width=True):
            session_counter.reset_session()
            st.rerun()
        
        st.markdown("---")
        st.markdown("*Developed with Streamlit*")
    
    # Main content based on navigation
    if page == "Single Scan":
        single_scan_mode(session_counter)
    elif page == "Continuous Scan":
        continuous_scan_mode(session_counter)
    elif page == "Session Summary":
        show_session_summary(session_counter)
    elif page == "Inventory Overview":
        inventory_overview()
    elif page == "File Management":
        file_management()

if __name__ == "__main__":
    main()