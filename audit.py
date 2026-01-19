import os
import re
import sys
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import unquote
from colorama import init, Fore, Style
from concurrent.futures import ThreadPoolExecutor

init(autoreset=True)

class SiteAuditor:
    def __init__(self, root_dir='.'):
        self.root_dir = Path(root_dir).resolve()
        self.html_files = []
        self.base_url = None
        self.keywords = []
        self.links_graph = {}  # target -> count
        self.pages_data = {}   # path -> {title, h1, schema, links, ...}
        self.external_links = set()
        self.issues = []
        self.score = 100

        # --- 配置：白名单与忽略项 ---
        self.ignore_url_patterns = [
            '/go/',           # 忽略短链跳转/重定向
            'cdn-cgi',        # Cloudflare 系统路径
            'javascript:', 
            'mailto:', 
            'tel:',
            '#'
        ]
        self.ignore_file_patterns = [
            'google',         # 忽略 Google 验证文件 (文件名包含 google)
            '404.html'        # 忽略 404 页面 (本身就是孤岛)
        ]

    def log(self, msg, level="INFO"):
        color = Fore.CYAN
        if level == "WARN": color = Fore.YELLOW
        if level == "ERROR": color = Fore.RED
        if level == "SUCCESS": color = Fore.GREEN
        if level == "SEO": color = Fore.MAGENTA
        if level == "DATA": color = Fore.BLUE
        print(f"{color}[{level}] {msg}{Style.RESET_ALL}")

    def auto_config(self):
        index_path = self.root_dir / 'index.html'
        if not index_path.exists():
            self.log("index.html not found! Running in limited mode.", "WARN")
            return

        try:
            with open(index_path, 'r', encoding='utf-8', errors='ignore') as f:
                soup = BeautifulSoup(f, 'html.parser')
                
                # Canonical
                canonical = soup.find('link', rel='canonical')
                if canonical and canonical.get('href'):
                    self.base_url = canonical['href']
                    self.log(f"Detected Base URL: {self.base_url}", "SUCCESS")
                
                # Keywords
                meta_kw = soup.find('meta', attrs={'name': 'keywords'})
                if meta_kw:
                    self.keywords = [k.strip() for k in meta_kw.get('content', '').split(',')]
                    self.log(f"Keywords: {', '.join(self.keywords)}", "INFO")
        except Exception as e:
            self.log(f"Config Error: {e}", "ERROR")

    def resolve_file_path(self, current_file_path, href):
        """
        智能解析：尝试找到 href 对应的本地文件。
        支持根路径 (/blog) 和相对路径 (../blog) 的解析。
        """
        # 移除 query参数 和 锚点
        clean_href = href.split('?')[0].split('#')[0]
        
        # 1. 确定搜索的基础路径
        if clean_href.startswith('/'):
            # 根路径：基于 self.root_dir
            search_path = self.root_dir / clean_href.lstrip('/')
        else:
            # 相对路径：基于当前文件所在目录
            search_path = current_file_path.parent / clean_href

        # 2. 尝试匹配文件
        candidates = [
            search_path,                              # 原样 (e.g. /image.png)
            search_path.with_suffix('.html'),         # 加 .html (Clean URL)
            search_path / 'index.html'                # 文件夹形式 (Pretty URL)
        ]

        # 如果 search_path 已经是 .html 结尾，candidates[1] 会重复，但这无所谓
        for candidate in candidates:
            # resolve() 处理 ../ 等相对符号，但为了防止跳出根目录报错，加 try
            try:
                candidate_resolved = candidate.resolve()
                if candidate_resolved.exists() and candidate_resolved.is_file():
                    return candidate_resolved
            except (FileNotFoundError, RuntimeError):
                continue
        
        return None

    def scan_files(self):
        all_files = self.root_dir.rglob('*.html')
        # 过滤掉 .git, node_modules 以及 ignore_file_patterns 中的文件
        self.html_files = []
        for f in all_files:
            if '.git' in f.parts or 'node_modules' in f.parts:
                continue
            if any(ign in f.name for ign in self.ignore_file_patterns):
                continue
            self.html_files.append(f)
        
        self.log(f"Scanning {len(self.html_files)} HTML files...", "INFO")
        
        for file_path in self.html_files:
            try:
                rel_path = "/" + str(file_path.relative_to(self.root_dir)).replace(os.sep, '/')
                
                # 初始化入度计数
                if rel_path not in self.links_graph:
                    self.links_graph[rel_path] = 0

                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    soup = BeautifulSoup(f, 'html.parser')
                    
                    # --- SEO 检查 ---
                    h1_tags = soup.find_all('h1')
                    schema = soup.find('script', type='application/ld+json')
                    nav_bread = soup.find(attrs={'aria-label': 'breadcrumb'}) or soup.find(class_=re.compile('breadcrumb', re.I))
                    
                    self.pages_data[rel_path] = {'has_h1': bool(h1_tags), 'has_schema': bool(schema)}

                    if len(h1_tags) == 0:
                        self.issues.append({'type': 'Semantic', 'msg': f"Missing H1: {rel_path}", 'deduct': 5})
                    elif len(h1_tags) > 1:
                        self.issues.append({'type': 'Semantic', 'msg': f"Multiple H1s: {rel_path}", 'deduct': 2}) # 降权扣分
                    if not schema:
                         self.issues.append({'type': 'Schema', 'msg': f"Missing Schema: {rel_path}", 'deduct': 2}) # 降权扣分

                    # --- 链接提取与检查 ---
                    for a in soup.find_all('a', href=True):
                        href = unquote(a['href'].strip())
                        
                        # A. 检查忽略名单
                        if any(pattern in href for pattern in self.ignore_url_patterns):
                            continue

                        # B. 外部链接
                        if href.startswith(('http://', 'https://')):
                            if self.base_url and href.startswith(self.base_url):
                                # 包含了本站域名，视为内部链接处理，但也给个警告
                                self.issues.append({'type': 'URL_Strategy', 'msg': f"Absolute internal URL: {rel_path} -> {href}", 'deduct': 1})
                                # 尝试转为相对路径继续检查（去掉域名部分）
                                href = href.replace(self.base_url, '/')
                            else:
                                self.external_links.add(href)
                                continue

                        # C. URL 规范性检查 (Warnings)
                        if not href.startswith('/'):
                             # 只是警告，不再导致死链误判，因为下面 resolve_file_path 会处理它
                             self.issues.append({'type': 'URL_Strategy', 'msg': f"Relative path usage: {rel_path} -> {href}", 'deduct': 2})
                        
                        if href.endswith('.html') or 'index.html' in href:
                             self.issues.append({'type': 'Clean_URL', 'msg': f"Dirty URL (.html): {rel_path} -> {href}", 'deduct': 2})

                        # D. 内部死链验证 (关键修复)
                        target_file = self.resolve_file_path(file_path, href)
                        
                        if target_file:
                            # 链接有效，记录权重传递
                            target_rel = "/" + str(target_file.relative_to(self.root_dir)).replace(os.sep, '/')
                            self.links_graph[target_rel] = self.links_graph.get(target_rel, 0) + 1
                        else:
                            # 真的找不到文件
                            self.issues.append({'type': 'Broken_Link', 'msg': f"Dead Link: {rel_path} -> {href}", 'deduct': 10})

            except Exception as e:
                self.log(f"Error parsing {file_path}: {e}", "ERROR")

    def check_external_links(self):
        if not self.external_links: return
        self.log(f"Checking {len(self.external_links)} external links (Async)...", "INFO")
        
        def check_url(url):
            try:
                headers = {'User-Agent': 'Mozilla/5.0 (compatible; SeoAuditor/2.0)'}
                r = requests.head(url, timeout=5, allow_redirects=True, headers=headers)
                if r.status_code >= 400:
                    # 有些服务器不支持 HEAD，重试一次 GET
                    if r.status_code == 405 or r.status_code == 403:
                         r = requests.get(url, timeout=5, headers=headers, stream=True)
                         if r.status_code >= 400: return (url, r.status_code)
                    else:
                        return (url, r.status_code)
            except:
                return (url, "Connect Error")
            return None

        with ThreadPoolExecutor(max_workers=10) as executor:
            results = executor.map(check_url, self.external_links)
        
        for res in results:
            if res:
                self.issues.append({'type': 'External_Dead', 'msg': f"External 404: {res[0]} ({res[1]})", 'deduct': 5})

    def analyze_structure(self):
        # 检查孤岛 (只检查我们实际扫描到的文件)
        # index.html 不是孤岛
        for page_rel in self.links_graph.keys():
            if page_rel == '/index.html': continue
            
            # 如果不在我们扫描的 html_files 列表中，说明可能是被引用的资源文件，忽略
            # 这里简化逻辑：只要 links_graph 里计数为 0 且它是被扫描到的页面
            if self.links_graph[page_rel] == 0:
                 # 再次确认不是忽略文件
                 if not any(ign in page_rel for ign in self.ignore_file_patterns):
                    self.issues.append({'type': 'Orphan', 'msg': f"Orphan Page (0 Inbound): {page_rel}", 'deduct': 5})
        
    def print_report(self):
        print("\n" + "="*40)
        print(f" AUDIT REPORT (Optimized) ")
        print("="*40)

        deductions = {}
        
        for issue in self.issues:
            # 聚合相同类型的扣分，防止分数溢出
            self.score -= issue['deduct']
            level = "ERROR"
            if issue['deduct'] <= 2: level = "WARN"
            if issue['type'] in ['Semantic', 'Schema']: level = "SEO"
            
            self.log(f"[{issue['type']}] {issue['msg']}", level)

        self.score = max(0, self.score)

        print("-" * 40)
        print(Fore.MAGENTA + "Top Pages by Inbound Links:")
        # 过滤掉不存在于 pages_data 的键（防止引用了非HTML资源干扰列表）
        valid_ranks = {k:v for k,v in self.links_graph.items() if k in self.pages_data or k == '/index.html'}
        sorted_pages = sorted(valid_ranks.items(), key=lambda item: item[1], reverse=True)[:10]
        for page, count in sorted_pages:
            print(f"  {count} links -> {page}")

        print("-" * 40)
        color = Fore.GREEN if self.score > 80 else (Fore.YELLOW if self.score > 50 else Fore.RED)
        print(f"{Style.BRIGHT}FINAL SEO SCORE: {color}{self.score}/100{Style.RESET_ALL}")

if __name__ == "__main__":
    auditor = SiteAuditor()
    auditor.auto_config()
    auditor.scan_files()
    auditor.check_external_links() 
    auditor.analyze_structure()
    auditor.print_report()