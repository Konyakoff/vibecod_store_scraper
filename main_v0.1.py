import streamlit as st
import pandas as pd
import re
import requests
import time
from app_store_scraper import AppStore

st.set_page_config(page_title="App Store Scraper", page_icon="🍏", layout="wide")

def get_app_details(input_str: str):
    """Извлекает ID и системное имя приложения."""
    app_id = None
    app_name = 'app'
    
    match_url = re.search(r'/app/(.*?)/id(\d+)', input_str)
    if match_url:
        return match_url.group(1), int(match_url.group(2))

    match_id = re.search(r'id(\d+)', input_str)
    if match_id:
        app_id = int(match_id.group(1))
    elif input_str.isdigit():
        app_id = int(input_str)

    if app_id:
        try:
            res = requests.get(f"https://itunes.apple.com/lookup?id={app_id}&country=ru", timeout=5).json()
            if res.get('resultCount', 0) > 0:
                track_url = res['results'][0]['trackViewUrl']
                match = re.search(r'/app/(.*?)/id', track_url)
                if match:
                    app_name = match.group(1)
        except Exception:
            pass
        return app_name, app_id

    return None, None

def get_reviews_rss(app_id: int, country: str = 'ru', limit: int = 500):
    """Резервный метод парсинга через официальный RSS (100% обход блокировок IP)."""
    reviews = []
    # RSS Apple отдает максимум 10 страниц по 50 отзывов
    max_pages = min(11, (limit // 50) + 2) 
    
    for page in range(1, max_pages):
        url = f"https://itunes.apple.com/{country}/rss/customerreviews/page={page}/id={app_id}/sortby=mostrecent/json"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                break
                
            data = response.json()
            entries = data.get('feed', {}).get('entry', [])
            
            if not entries:
                break
                
            # Пропускаем первый элемент на 1-й странице (это инфо о самом приложении)
            start_idx = 1 if page == 1 else 0
            
            for entry in entries[start_idx:]:
                review = {
                    'date': entry.get('updated', {}).get('label', ''),
                    'rating': int(entry.get('im:rating', {}).get('label', 0)),
                    'userName': entry.get('author', {}).get('name', {}).get('label', ''),
                    'title': entry.get('title', {}).get('label', ''),
                    'review': entry.get('content', {}).get('label', ''),
                    'version': entry.get('im:version', {}).get('label', 'Неизвестно')
                }
                reviews.append(review)
                if len(reviews) >= limit:
                    return reviews
                    
            time.sleep(0.5) # Задержка, чтобы не спамить запросами
        except Exception:
            break
            
    return reviews

@st.cache_data(show_spinner=False)
def fetch_reviews(app_name: str, app_id: int, limit: int):
    """Пытается спарсить через библиотеку, при неудаче использует RSS."""
    # Попытка 1: Основная библиотека
    app = AppStore(country='ru', app_name=app_name, app_id=app_id)
    try:
        app.review(how_many=limit)
        if app.reviews:
            return app.reviews, "main"
    except Exception:
        pass
        
    # Попытка 2: Резервный RSS
    rss_reviews = get_reviews_rss(app_id, limit=limit)
    return rss_reviews, "rss"

def main():
    st.title("🍏 App Store Reviews Scraper")
    st.markdown("Соберите отзывы из App Store (регион: **Россия**) и скачайте их в CSV.")

    with st.container():
        user_input = st.text_input("Введите ID приложения или ссылку:", placeholder="Например: id564177498")
        limit = st.slider("Количество отзывов (макс. 500 для RSS-метода):", min_value=50, max_value=10000, value=500, step=50)
        start_parsing = st.button("Парсить отзывы", type="primary")

    if start_parsing:
        if not user_input:
            st.error("Пожалуйста, введите ссылку или ID приложения.")
            return

        app_name, app_id = get_app_details(user_input)
        
        if not app_id:
            st.error("Некорректный формат. Не удалось извлечь ID.")
            return

        with st.spinner(f"Собираем отзывы для ID {app_id}..."):
            try:
                raw_reviews, method = fetch_reviews(app_name, app_id, limit)
                
                if not raw_reviews:
                    st.error("Не удалось найти отзывы. Проверьте ID или попробуйте позже.")
                    return
                
                df = pd.DataFrame(raw_reviews)
                
                columns_mapping = {
                    'date': 'Дата', 'rating': 'Оценка (звезды)', 'userName': 'Имя пользователя',
                    'title': 'Заголовок отзыва', 'review': 'Текст отзыва', 'version': 'Версия приложения'
                }
                df = df[[col for col in columns_mapping.keys() if col in df.columns]]
                df = df.rename(columns=columns_mapping)
                
                # Приводим даты к нормальному виду, если нужно
                try:
                    df['Дата'] = pd.to_datetime(df['Дата']).dt.strftime('%Y-%m-%d %H:%M:%S')
                except Exception:
                    pass

                if method == "rss":
                    st.warning("⚠️ Основной парсер заблокирован Apple (IP дата-центра). Использован резервный RSS-канал (лимит 500 последних отзывов).")
                
                st.success(f"Успешно собрано {len(df)} отзывов!")

                avg_rating = df['Оценка (звезды)'].mean()
                col1, col2 = st.columns(2)
                col1.metric("Собрано отзывов", len(df))
                col2.metric("Средняя оценка", f"⭐ {avg_rating:.2f} / 5.0")

                st.subheader("Превью данных:")
                st.dataframe(df.head(10), use_container_width=True)

                csv_data = df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                st.download_button("📥 Скачать полный CSV-файл", data=csv_data, file_name=f"reviews_{app_id}.csv", mime="text/csv")

            except Exception as e:
                st.error(f"Произошла ошибка при получении данных: {e}")

if __name__ == "__main__":
    main()