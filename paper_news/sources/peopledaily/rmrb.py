import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

DEFAULT_BASE_URL = 'http://paper.people.com.cn/rmrb/pc'


def fetch_url(url: str) -> str:
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/68.0.3440.106 Safari/537.36',
    }
    r = requests.get(url, headers=headers, timeout=30, proxies={'http': None, 'https': None})
    r.raise_for_status()
    r.encoding = r.apparent_encoding
    return r.text


def get_page_list(year: str, month: str, day: str, base_url: str = DEFAULT_BASE_URL):
    base_url = base_url.rstrip('/')
    base_layout = f'{base_url}/layout/{year}{month}/{day}/'
    url = urljoin(base_layout, 'node_01.html')
    html = fetch_url(url)
    bsobj = BeautifulSoup(html, 'html.parser')
    temp = bsobj.find('div', attrs={'id': 'pageList'})
    if temp:
        page_list = temp.ul.find_all('div', attrs={'class': 'right_title-name'})
    else:
        swiper = bsobj.find('div', attrs={'class': 'swiper-container'})
        page_list = [] if not swiper else swiper.find_all('div', attrs={'class': 'swiper-slide'})

    link_list = []
    for page in page_list:
        a = page.find('a')
        if not a:
            continue
        link = a.get('href', '')
        name = a.get_text(strip=True)
        valid_name = ''.join(i for i in name if i not in r'\/:*?"<>|')
        page_url = urljoin(base_layout, link)
        link_list.append((page_url, valid_name))
    return link_list


def get_title_list(year: str, month: str, day: str, page_url: str, base_url: str = DEFAULT_BASE_URL):
    html = fetch_url(page_url)
    bsobj = BeautifulSoup(html, 'html.parser')
    temp = bsobj.find('div', attrs={'id': 'titleList'})
    if temp:
        title_list = temp.ul.find_all('li')
    else:
        news_list = bsobj.find('ul', attrs={'class': 'news-list'})
        title_list = [] if not news_list else news_list.find_all('li')

    link_list = []
    base_url = base_url.rstrip('/')
    content_base = f'{base_url}/content/{year}{month}/{day}/'
    for title in title_list:
        for a in title.find_all('a'):
            link = a.get('href', '')
            if 'content' in link:
                abs_url = urljoin(content_base, link)
                link_list.append(abs_url)
    return link_list


def parse_article(html: str):
    bsobj = BeautifulSoup(html, 'html.parser')
    title_text = (bsobj.h1.get_text(strip=True) if bsobj.h1 else '')
    title_valid = ''.join(i for i in title_text if i not in r'\/:*?"<>|')
    h3 = bsobj.h3.get_text(strip=True) if bsobj.h3 else ''
    h2 = bsobj.h2.get_text(strip=True) if bsobj.h2 else ''
    container = bsobj.find('div', attrs={'id': 'ozoom'})
    content_body = ''
    if container:
        p_list = container.find_all('p')
        for p in p_list:
            content_body += p.get_text(strip=True) + '\n'
    else:
        # 兜底：收集所有 <p> 标签文本
        content_body = '\n'.join(p.get_text(strip=True) for p in bsobj.find_all('p'))
    summary = content_body.strip()
    content_full = ''
    if h3:
        content_full += h3 + '\n'
    content_full += (title_text + '\n') if title_text else ''
    if h2:
        content_full += h2 + '\n'
    content_full += content_body
    return content_full, title_valid, title_text, content_body, summary
