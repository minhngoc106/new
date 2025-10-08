import streamlit as st
import pandas as pd
import math
import json
import io
# Cần cài đặt pip install python-docx nếu chạy ngoài môi trường này
from docx import Document 
from google import genai
from google.genai.errors import APIError

# --- Cấu hình Trang Streamlit ---
st.set_page_config(
    page_title="App Đánh Giá Phương Án Kinh Doanh (DCF)",
    layout="wide"
)

st.title("💰 Ứng dụng Đánh Giá Phương Án Kinh Doanh (DCF)")
st.caption("Sử dụng Gemini AI để trích xuất dữ liệu từ file Word và phân tích hiệu quả dự án.")

# --- Thiết lập API Key (Để dễ dàng test, sử dụng input) ---
api_key = st.text_input("Nhập Khóa API Gemini của bạn (Yêu cầu cho AI)", type="password")

# --- Hàm đọc nội dung từ file Word (.docx) ---
def read_docx_content(docx_file):
    """Đọc nội dung văn bản từ tệp .docx đã tải lên."""
    try:
        # docx.Document cần một file-like object
        document = Document(io.BytesIO(docx_file.getvalue()))
        text = "\n".join([paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()])
        return text
    except Exception as e:
        st.error(f"Lỗi khi đọc file DOCX. Vui lòng đảm bảo đó là file Word hợp lệ. Chi tiết: {e}")
        return None

# --- Chức năng 1: Trích xuất Dữ liệu Cấu trúc bằng AI ---
def extract_financial_data(doc_text, api_key):
    """Gửi nội dung văn bản đến Gemini API để trích xuất các chỉ số tài chính theo cấu trúc JSON."""
    if not api_key:
        st.error("Vui lòng nhập Khóa API Gemini.")
        return None
    if not doc_text:
        st.error("Nội dung văn bản trống, không thể trích xuất.")
        return None
        
    try:
        client = genai.Client(api_key=api_key)
        model_name = 'gemini-2.5-flash-preview-05-20'

        # Định nghĩa Schema JSON cho đầu ra
        json_schema = {
            "type": "OBJECT",
            "properties": {
                "investment_capital": {"type": "NUMBER", "description": "Tổng vốn đầu tư ban đầu (VND hoặc USD), chỉ lấy giá trị số."},
                "project_lifespan": {"type": "INTEGER", "description": "Dòng đời dự án theo năm."},
                "annual_revenue": {"type": "NUMBER", "description": "Doanh thu hàng năm trung bình, chỉ lấy giá trị số."},
                "annual_cost": {"type": "NUMBER", "description": "Chi phí hoạt động hàng năm trung bình (trừ chi phí khấu hao), chỉ lấy giá trị số."},
                "wacc": {"type": "NUMBER", "description": "Chi phí vốn bình quân (WACC) dưới dạng số thập phân (ví dụ: 0.1 cho 10%)."},
                "tax_rate": {"type": "NUMBER", "description": "Thuế suất doanh nghiệp dưới dạng số thập phân (ví dụ: 0.2 cho 20%)."}
            },
            "required": ["investment_capital", "project_lifespan", "annual_revenue", "annual_cost", "wacc", "tax_rate"]
        }
        
        system_prompt = (
            "Bạn là một chuyên gia phân tích tài chính. Hãy trích xuất các thông tin sau từ văn bản kinh doanh "
            "đã cung cấp và chỉ trả về dưới định dạng JSON theo schema đã cho. "
            "Đảm bảo tất cả các giá trị là số và đã được quy đổi về cùng một đơn vị (ví dụ: 'tỷ VND' thành '1000000000')."
        )

        user_prompt = f"Trích xuất các thông tin tài chính sau từ tài liệu Word:\n\n{doc_text}"

        response = client.models.generate_content(
            model=model_name,
            contents=[{"parts": [{"text": user_prompt}]}],
            config={
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "responseMimeType": "application/json",
                "responseSchema": json_schema
            }
        )
        
        # Parse chuỗi JSON
        return json.loads(response.text)

    except APIError as e:
        st.error(f"Lỗi gọi Gemini API: Vui lòng kiểm tra Khóa API hoặc giới hạn sử dụng. Chi tiết: {e}")
    except json.JSONDecodeError:
        st.error("Lỗi giải mã JSON từ AI. Vui lòng thử lại hoặc chỉnh sửa nội dung tài liệu rõ ràng hơn.")
    except Exception as e:
        st.error(f"Đã xảy ra lỗi không xác định trong quá trình trích xuất: {e}")
    return None

# --- Chức năng 2 & 3: Xây dựng Dòng Tiền & Tính Toán Chỉ số DCF ---
def calculate_dcf_metrics(data):
    """Tính toán Bảng Dòng Tiền, NPV, IRR, PP, và DPP."""
    
    # Lấy dữ liệu đã được trích xuất
    I0 = data['investment_capital']
    N = data['project_lifespan']
    R_annual = data['annual_revenue']
    C_annual = data['annual_cost']
    WACC = data['wacc']
    T = data['tax_rate']
    
    # 1. Xây dựng Bảng Dòng Tiền
    df_data = []
    
    # Dòng tiền năm 0 (Initial Investment)
    df_data.append({
        'Năm': 0, 
        'Doanh thu (R)': 0, 
        'Chi phí (C)': 0,
        'Lợi nhuận trước thuế (EBT)': 0, 
        'Thuế (T)': 0,
        'Lợi nhuận sau thuế (EAT)': 0, 
        'Dòng tiền hoạt động (CF)': -I0, 
        'Giá trị chiết khấu (DF)': 1.0, 
        'Dòng tiền chiết khấu (DCF)': -I0, 
        'CF Tích lũy': -I0
    })
    
    cumulative_cf = -I0
    cumulative_dcf = -I0
    
    for t in range(1, N + 1):
        EBT = R_annual - C_annual
        Tax_amount = EBT * T if EBT > 0 else 0
        EAT = EBT - Tax_amount
        CF = EAT # Giả định dòng tiền thuần = Lợi nhuận sau thuế (bỏ qua Khấu hao, Vốn lưu động)
        
        # Tính chiết khấu
        DF = 1.0 / (1 + WACC)**t
        DCF = CF * DF
        
        cumulative_cf += CF
        cumulative_dcf += DCF
        
        df_data.append({
            'Năm': t, 
            'Doanh thu (R)': R_annual, 
            'Chi phí (C)': C_annual,
            'Lợi nhuận trước thuế (EBT)': EBT, 
            'Thuế (T)': Tax_amount,
            'Lợi nhuận sau thuế (EAT)': EAT, 
            'Dòng tiền hoạt động (CF)': CF, 
            'Giá trị chiết khấu (DF)': DF, 
            'Dòng tiền chiết khấu (DCF)': DCF, 
            'CF Tích lũy': cumulative_cf
        })
        
    df_cashflow = pd.DataFrame(df_data)

    # 2. Tính toán các chỉ số
    NPV = df_cashflow['Dòng tiền chiết khấu (DCF)'].sum()
    
    # Tính Payback Period (PP) và Discounted Payback Period (DPP)
    def calculate_payback(df, cf_column):
        """Tính thời gian hoàn vốn (PP hoặc DPP)"""
        I_initial = abs(df.iloc[0]['Dòng tiền hoạt động (CF)'])
        cumulative_list = df[cf_column].cumsum().tolist()
        
        # Tìm năm hoàn vốn (năm đầu tiên CF tích lũy >= 0)
        payback_year = next((i for i, c in enumerate(cumulative_list) if c >= 0), N)
        
        if payback_year == 0:
            return 0
        elif payback_year < N:
            # Hoàn vốn trong năm
            prev_cumulative = cumulative_list[payback_year - 1]
            cf_at_payback_year = df.iloc[payback_year][cf_column]
            
            # Công thức tính thời gian hoàn vốn: Năm hoàn vốn - 1 + (Số tiền cần hoàn vốn / Dòng tiền của năm đó)
            fractional_year = abs(prev_cumulative) / cf_at_payback_year
            return (payback_year - 1) + fractional_year
        else:
            return N # Nếu không hoàn vốn trong dòng đời dự án
        
    PP = calculate_payback(df_cashflow, 'Dòng tiền hoạt động (CF)')
    DPP = calculate_payback(df_cashflow, 'Dòng tiền chiết khấu (DCF)')
    
    # Tính IRR (sử dụng phương pháp Nội suy tuyến tính đơn giản cho 2 điểm chiết khấu)
    # Đây là một ước tính đơn giản vì không dùng thư viện chuyên dụng
    # IRR thực tế đòi hỏi thuật toán phức tạp hơn (ví dụ: bisection method)
    IRR = "Cần thư viện numpy_financial để tính chính xác"
    
    # Kết quả tính toán (Chỉ số)
    metrics = {
        'Vốn Đầu tư (I0)': I0,
        'Dòng đời Dự án (Năm)': N,
        'WACC': WACC,
        'Thuế suất': T,
        'NPV': NPV,
        'IRR': IRR,
        'Thời gian hoàn vốn (PP)': PP,
        'Thời gian hoàn vốn chiết khấu (DPP)': DPP
    }
    
    return df_cashflow, metrics

# --- Chức năng 4: Phân tích Chỉ số Hiệu quả bằng AI ---
def analyze_project_metrics(metrics, df_cashflow, api_key):
    """Gửi các chỉ số và bảng dòng tiền đến Gemini API để nhận phân tích."""
    if not api_key:
        return "Lỗi: Không tìm thấy Khóa API Gemini."

    try:
        client = genai.Client(api_key=api_key)
        model_name = 'gemini-2.5-flash-preview-05-20' 
        
        # Chuẩn bị dữ liệu cho AI
        metrics_text = json.dumps(metrics, indent=2, ensure_ascii=False)
        cashflow_text = df_cashflow.to_markdown(index=False)

        prompt = f"""
        Bạn là một chuyên gia phân tích đầu tư và tài chính. Dựa trên các chỉ số và bảng dòng tiền sau, hãy đưa ra một đánh giá chuyên sâu và khách quan (khoảng 3 đoạn) về tính khả thi của phương án kinh doanh này.
        
        **Tập trung vào:**
        1. **Khả năng sinh lời:** Đánh giá NPV.
        2. **Rủi ro và Thanh khoản:** Phân tích PP và DPP (so sánh với dòng đời dự án).
        3. **Khuyến nghị:** Phương án này có nên được chấp nhận hay không?
        
        **Các chỉ số hiệu quả:**
        {metrics_text}
        
        **Bảng Dòng Tiền Hoạt Động:**
        {cashflow_text}
        """

        response = client.models.generate_content(
            model=model_name,
            contents=prompt
        )
        return response.text

    except APIError as e:
        return f"Lỗi gọi Gemini API: {e}"
    except Exception as e:
        return f"Đã xảy ra lỗi không xác định khi yêu cầu phân tích: {e}"

# =========================================================================
# --- Streamlit UI và Logic chính ---
# =========================================================================

uploaded_file = st.file_uploader(
    "1. Tải lên file Word (.docx) chứa Phương án Kinh doanh:",
    type=['docx']
)

if uploaded_file is not None and api_key:
    # --- Trạng thái xử lý ---
    if 'extracted_data' not in st.session_state:
        st.session_state['extracted_data'] = None
    
    # Nút bấm để thực hiện thao tác lọc dữ liệu
    if st.button("🔴 1. Lọc Dữ liệu Tài chính bằng AI"):
        doc_text = read_docx_content(uploaded_file)
        if doc_text:
            with st.spinner('AI đang đọc và trích xuất dữ liệu tài chính (Dạng JSON)...'):
                extracted_data = extract_financial_data(doc_text, api_key)
                if extracted_data:
                    st.session_state['extracted_data'] = extracted_data
                    st.success("Trích xuất dữ liệu thành công!")

    # --- Hiển thị dữ liệu đã trích xuất ---
    if st.session_state['extracted_data']:
        data = st.session_state['extracted_data']
        
        st.subheader("Trích xuất Thành công (Dữ liệu đầu vào)")
        
        col_inv, col_life, col_wacc, col_tax = st.columns(4)
        col_rev, col_cost, _, _ = st.columns(4)
        
        with col_inv:
            st.metric("Vốn Đầu tư (I0)", f"{data['investment_capital']:,.0f}")
        with col_life:
            st.metric("Dòng đời Dự án (Năm)", data['project_lifespan'])
        with col_wacc:
            st.metric("WACC", f"{data['wacc']*100:.2f}%")
        with col_tax:
            st.metric("Thuế suất", f"{data['tax_rate']*100:.2f}%")
            
        with col_rev:
            st.metric("Doanh thu Hàng năm", f"{data['annual_revenue']:,.0f}")
        with col_cost:
            st.metric("Chi phí Hàng năm", f"{data['annual_cost']:,.0f}")
            
        st.divider()

        # --- Chức năng 2 & 3: Tính toán và Hiển thị Bảng Dòng Tiền & Chỉ số ---
        try:
            df_cashflow, metrics = calculate_dcf_metrics(data)

            st.subheader("2. Bảng Dòng Tiền Hoạt Động và 3. Các Chỉ số Đánh giá")
            
            # Hiển thị Bảng Dòng Tiền
            st.markdown("##### Bảng Dòng Tiền (CF) & Dòng Tiền Chiết Khấu (DCF)")
            st.dataframe(df_cashflow.style.format({
                'Doanh thu (R)': '{:,.0f}',
                'Chi phí (C)': '{:,.0f}',
                'Lợi nhuận trước thuế (EBT)': '{:,.0f}',
                'Thuế (T)': '{:,.0f}',
                'Lợi nhuận sau thuế (EAT)': '{:,.0f}',
                'Dòng tiền hoạt động (CF)': '{:,.0f}',
                'Giá trị chiết khấu (DF)': '{:.4f}',
                'Dòng tiền chiết khấu (DCF)': '{:,.0f}',
                'CF Tích lũy': '{:,.0f}'
            }), use_container_width=True)

            # Hiển thị các chỉ số đánh giá
            st.markdown("##### Các Chỉ số Hiệu quả Dự án")
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("NPV (Giá trị hiện tại ròng)", f"{metrics['NPV']:,.0f}", 
                          delta="Dự án Khả thi" if metrics['NPV'] > 0 else "Dự án Không khả thi")
            with col2:
                st.metric("Thời gian hoàn vốn (PP)", f"{metrics['Thời gian hoàn vốn (PP)']:.2f} năm")
            with col3:
                st.metric("Thời gian hoàn vốn chiết khấu (DPP)", f"{metrics['Thời gian hoàn vốn chiết khấu (DPP)']:.2f} năm")
            with col4:
                st.metric("IRR", metrics['IRR'])
                
            st.divider()

            # --- Chức năng 4: Phân tích của AI ---
            st.subheader("4. Phân tích Chuyên sâu về Dự án (AI)")
            if st.button("🧠 Yêu cầu AI Phân tích Hiệu quả Dự án"):
                with st.spinner('Đang gửi dữ liệu đến AI để phân tích và đánh giá...'):
                    analysis = analyze_project_metrics(metrics, df_cashflow, api_key)
                    st.info(analysis)

        except Exception as e:
            st.error(f"Lỗi xảy ra trong quá trình tính toán: {e}. Vui lòng kiểm tra dữ liệu trích xuất.")
            
elif uploaded_file is None:
     st.info("Vui lòng tải lên file Word và nhập API Key để bắt đầu.")
elif not api_key:
     st.warning("Vui lòng nhập Khóa API Gemini của bạn để sử dụng chức năng AI.")
