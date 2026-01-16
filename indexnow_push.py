import requests
import xml.etree.ElementTree as ET
import json

# 配置信息
HOST = "mjmai.top"
KEY = "d18753b123184422bd671c0d6263beff"
KEY_LOCATION = f"https://{HOST}/{KEY}.txt"
SITEMAP_FILE = "sitemap.xml"
INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"

def get_urls_from_sitemap(sitemap_path):
    """从 sitemap.xml 提取所有 URL"""
    try:
        tree = ET.parse(sitemap_path)
        root = tree.getroot()
        # sitemap 命名空间
        namespace = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        urls = []
        for url in root.findall('ns:url', namespace):
            loc = url.find('ns:loc', namespace)
            if loc is not None:
                urls.append(loc.text)
        return urls
    except Exception as e:
        print(f"读取 sitemap 失败: {e}")
        return []

def push_to_indexnow(urls):
    """推送 URL 到 IndexNow"""
    if not urls:
        print("没有找到需要推送的 URL")
        return

    payload = {
        "host": HOST,
        "key": KEY,
        "keyLocation": KEY_LOCATION,
        "urlList": urls
    }

    headers = {
        "Content-Type": "application/json; charset=utf-8"
    }

    try:
        response = requests.post(INDEXNOW_ENDPOINT, data=json.dumps(payload), headers=headers)
        
        # IndexNow 返回 200 或 202 都表示请求已被接收
        if response.status_code in [200, 202]:
            print("✅ 推送成功！IndexNow 已接收 URL 列表。")
            print(f"共推送 {len(urls)} 个链接：")
            for url in urls:
                print(f" - {url}")
        else:
            print(f"❌ 推送失败。状态码: {response.status_code}")
            print(f"响应内容: {response.text}")
            
    except Exception as e:
        print(f"❌ 发送请求时出错: {e}")

if __name__ == "__main__":
    print(f"正在读取 {SITEMAP_FILE} ...")
    urls = get_urls_from_sitemap(SITEMAP_FILE)
    
    if urls:
        print(f"找到 {len(urls)} 个 URL，准备推送...")
        push_to_indexnow(urls)
    else:
        print("未找到 URL，请检查 sitemap.xml 格式")
