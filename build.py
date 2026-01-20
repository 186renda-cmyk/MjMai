import os
import re
import json
import datetime
from pathlib import Path
from bs4 import BeautifulSoup
from difflib import SequenceMatcher

# ================= 配置区域 =================
BASE_URL = "https://mjmai.top"
SOURCE_FILE = "index.html"
BLOG_DIR = "blog"
IGNORE_DIRS = ['.git', 'node_modules', '__pycache__']
AUTHOR_NAME = "MjMai"
# ===========================================

class StaticSiteBuilder:
    def __init__(self, root_dir='.'):
        self.root_dir = Path(root_dir).resolve()
        self.header_html = None
        self.footer_html = None
        self.pages = [] 

    def log(self, msg):
        print(f"🔧 {msg}")

    def load_templates(self):
        """Extract Header and Footer from index.html"""
        source_path = self.root_dir / SOURCE_FILE
        if not source_path.exists():
            raise FileNotFoundError(f"Source file {SOURCE_FILE} not found!")

        with open(source_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')
            
            # Find header (try explicit ID first, then tag)
            header = soup.find('header', id='navbar') or soup.find('header') or soup.find('nav')
            footer = soup.find('footer')

            if header:
                self._normalize_links(header)
                self.header_html = header
                self.log("已提取并标准化 Header")
            
            if footer:
                self._normalize_links(footer)
                self.footer_html = footer
                self.log("已提取并标准化 Footer")

    def _normalize_links(self, soup_element):
        """Convert all links to root-relative paths"""
        for a in soup_element.find_all('a', href=True):
            href = a['href']
            if href.startswith(('http', 'mailto:', 'tel:')):
                continue
            
            # Handle anchor links on home page that need to be full paths on other pages
            # e.g. #pricing -> /#pricing
            if href.startswith('#'):
                href = '/' + href
            
            # Remove .html extension if present (optional, but good for clean URLs)
            if href.endswith('.html'):
                href = href[:-5]
            
            # Ensure it starts with /
            if not href.startswith('/'):
                href = '/' + href
                
            a['href'] = href

    def scan_content(self):
        """Scan both blog directory and root directory for HTML files"""
        self.pages = [] # Reset
        
        # 1. Scan Blog Articles (Type A)
        blog_path = self.root_dir / BLOG_DIR
        if blog_path.exists():
            for file_path in blog_path.glob('*.html'):
                if file_path.name == 'index.html': continue
                self._parse_and_add_page(file_path, page_type='article')

        # 2. Scan Root Pages (Type B)
        for file_path in self.root_dir.glob('*.html'):
            if file_path.name == SOURCE_FILE: continue # Skip index.html
            self._parse_and_add_page(file_path, page_type='page')

        # Sort by date descending (mainly for articles, but keeps list consistent)
        self.pages.sort(key=lambda x: x['date'], reverse=True)
        self.log(f"已扫描 {len(self.pages)} 个页面 (含文章与单页)")

    def _parse_and_add_page(self, file_path, page_type):
        """Helper to parse a file and add to pages list"""
        with open(file_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')
            
            # Title
            title = soup.title.string.strip() if soup.title else file_path.stem
            
            # Description
            desc_tag = soup.find('meta', attrs={'name': 'description'})
            desc = desc_tag['content'].strip() if desc_tag else ""
            
            # Keywords
            kw_tag = soup.find('meta', attrs={'name': 'keywords'})
            keywords = kw_tag['content'].strip() if kw_tag else ""
            
            # H1
            h1_tag = soup.find('h1')
            h1 = h1_tag.get_text().strip() if h1_tag else title

            # Date
            mtime = datetime.datetime.fromtimestamp(file_path.stat().st_mtime)
            date_obj = mtime
            
            time_tag = soup.find('time')
            if time_tag and time_tag.has_attr('datetime'):
                try:
                    date_obj = datetime.datetime.strptime(time_tag['datetime'][:10], "%Y-%m-%d")
                except:
                    pass
            
            pub_time_meta = soup.find('meta', property='article:published_time')
            if pub_time_meta:
                try:
                    date_obj = datetime.datetime.strptime(pub_time_meta['content'][:10], "%Y-%m-%d")
                except:
                    pass

            date_iso = date_obj.isoformat()
            
            # URL
            if page_type == 'article':
                rel_url = f"/{BLOG_DIR}/{file_path.stem}"
            else:
                rel_url = f"/{file_path.stem}"
            
            self.pages.append({
                'path': file_path,
                'url': rel_url,
                'title': title,
                'h1': h1,
                'desc': desc,
                'keywords': keywords,
                'date': date_obj,
                'date_iso': date_iso,
                'type': page_type # 'article' or 'page'
            })

    def get_related_posts(self, current_page, limit=2):
        """Get related posts based on keyword matching (Only from Articles)"""
        if current_page['type'] != 'article': return []

        scores = []
        current_keywords = set(k.strip().lower() for k in current_page['keywords'].split(',') if k.strip())
        
        # Only recommend other ARTICLES
        articles = [p for p in self.pages if p['type'] == 'article']
        
        for other in articles:
            if other['path'] == current_page['path']: continue
            
            other_keywords = set(k.strip().lower() for k in other['keywords'].split(',') if k.strip())
            
            # Intersection count
            score = len(current_keywords.intersection(other_keywords))
            
            # Fallback to title similarity if no keyword overlap
            if score == 0:
                score = SequenceMatcher(None, current_page['title'], other['title']).ratio() * 0.5 
            
            scores.append((score, other))
            
        scores.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scores[:limit] if item[0] > 0]

    def generate_breadcrumb_html(self, title, page_type):
        """Generate semantic breadcrumbs based on page type"""
        if page_type == 'article':
            # Home > 教程资源 > Title
            html = f'''
            <nav aria-label="Breadcrumb" class="text-sm text-slate-400 mb-6">
                <ol class="flex flex-wrap items-center gap-2">
                    <li><a href="/" class="hover:text-blue-600 transition-colors">首页</a></li>
                    <li>/</li>
                    <li><a href="/blog/" class="hover:text-blue-600 transition-colors">教程资源</a></li>
                    <li>/</li>
                    <li><span class="text-slate-200">{title}</span></li>
                </ol>
            </nav>
            '''
        else:
            # Home > Title
            html = f'''
            <nav aria-label="Breadcrumb" class="text-sm text-slate-400 mb-6">
                <ol class="flex flex-wrap items-center gap-2">
                    <li><a href="/" class="hover:text-blue-600 transition-colors">首页</a></li>
                    <li>/</li>
                    <li><span class="text-slate-200">{title}</span></li>
                </ol>
            </nav>
            '''
        return html

    def generate_schema(self, page):
        """Generate JSON-LD Schema based on page type"""
        if page['type'] == 'article':
            schema = {
                "@context": "https://schema.org",
                "@type": "BlogPosting",
                "headline": page['h1'],
                "description": page['desc'],
                "image": [f"{BASE_URL}/logo.svg"], # Default image
                "datePublished": page['date_iso'],
                "author": {
                    "@type": "Organization",
                    "name": AUTHOR_NAME,
                    "url": BASE_URL
                },
                "publisher": {
                    "@type": "Organization",
                    "name": "MjMai",
                    "logo": {
                        "@type": "ImageObject",
                        "url": f"{BASE_URL}/logo.svg"
                    }
                },
                "mainEntityOfPage": {
                    "@type": "WebPage",
                    "@id": f"{BASE_URL}{page['url']}"
                },
                "breadcrumb": {
                    "@type": "BreadcrumbList",
                    "itemListElement": [
                        {
                            "@type": "ListItem",
                            "position": 1,
                            "name": "首页",
                            "item": BASE_URL
                        },
                        {
                            "@type": "ListItem",
                            "position": 2,
                            "name": "教程资源",
                            "item": f"{BASE_URL}/blog/"
                        },
                        {
                            "@type": "ListItem",
                            "position": 3,
                            "name": page['h1'],
                            "item": f"{BASE_URL}{page['url']}"
                        }
                    ]
                }
            }
        else:
            # Simple WebPage Schema for functional pages
            schema = {
                "@context": "https://schema.org",
                "@type": "WebPage",
                "name": page['h1'],
                "description": page['desc'],
                "url": f"{BASE_URL}{page['url']}",
                "breadcrumb": {
                    "@type": "BreadcrumbList",
                    "itemListElement": [
                        {
                            "@type": "ListItem",
                            "position": 1,
                            "name": "首页",
                            "item": BASE_URL
                        },
                        {
                            "@type": "ListItem",
                            "position": 2,
                            "name": page['h1'],
                            "item": f"{BASE_URL}{page['url']}"
                        }
                    ]
                }
            }
        return json.dumps(schema, ensure_ascii=False, indent=4)

    def generate_card_html(self, page):
        """Generate a card HTML for the article (for Index/List pages)"""
        # Simple random icon logic
        icons = ["💎", "🚀", "⚖️", "🎨", "📝", "🔥"]
        icon = icons[hash(page['title']) % len(icons)]
        
        colors = ["violet", "fuchsia", "blue", "emerald", "amber", "indigo"]
        color = colors[hash(page['title']) % len(colors)]
        
        html = f'''
        <article class="glass-card rounded-2xl overflow-hidden group hover:border-{color}-500/50 transition-all duration-300">
            <div class="h-48 bg-gradient-to-br from-{color}-900/50 to-slate-900 flex items-center justify-center relative overflow-hidden">
                <div class="absolute inset-0 bg-[url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAiIGhlaWdodD0iMjAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PGNpcmNsZSBjeD0iMSIgY3k9IjEiIHI9IjEiIGZpbGw9InJnYmEoMjU1LDI1NSwyNTUsMC4xKSIvPjwvc3ZnPg==')] opacity-30"></div>
                <div class="w-16 h-16 bg-{color}-600/20 rounded-2xl flex items-center justify-center text-{color}-400 text-3xl group-hover:scale-110 transition-transform duration-300">
                    {icon}
                </div>
            </div>
            <div class="p-6">
                <div class="flex items-center gap-2 mb-4 text-xs font-bold uppercase tracking-wider text-{color}-400">
                    <span>Article</span>
                    <span class="w-1 h-1 rounded-full bg-slate-600"></span>
                    <span>{page['date'].strftime('%Y-%m-%d')}</span>
                </div>
                <h3 class="text-xl font-bold text-white mb-3 group-hover:text-{color}-300 transition-colors">
                    <a href="{page['url']}">{page['h1']}</a>
                </h3>
                <p class="text-slate-400 text-sm mb-6 line-clamp-2">
                    {page['desc']}
                </p>
                <a href="{page['url']}" class="inline-flex items-center text-sm font-bold text-white hover:text-{color}-400 transition-colors">
                    阅读全文
                    <svg class="w-4 h-4 ml-1 transition-transform group-hover:translate-x-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 8l4 4m0 0l-4 4m4-4H3"></path></svg>
                </a>
            </div>
        </article>
        '''
        return html

    def process_pages(self):
        """Process each page (Article or Root Page)"""
        self.log("开始处理所有页面...")
        
        for page in self.pages:
            file_path = page['path']
            page_type = page['type']
            
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            soup = BeautifulSoup(content, 'html.parser')
            
            # === 1. Clean Up (清洗旧元素) ===
            
            # Remove Header
            if soup.body:
                first_nav = soup.body.find('nav', recursive=False)
                if not first_nav:
                     first_nav = soup.body.find('header', recursive=False)
                if first_nav:
                    first_nav.decompose()

            # Remove Footer
            if soup.body:
                footer_tag = soup.body.find('footer', recursive=False)
                if footer_tag:
                    footer_tag.decompose()

            # Remove Schema
            if soup.head:
                for s in soup.head.find_all('script', type='application/ld+json'):
                    s.decompose()

            # Remove Old Breadcrumbs
            for nav in soup.find_all('nav', attrs={'aria-label': 'Breadcrumb'}):
                nav.decompose()
            for nav in soup.find_all('nav', attrs={'aria-label': 'breadcrumb'}):
                nav.decompose()

            # Remove Old Related Posts (Strict Cleaning for ALL pages first)
            related_div = soup.find('div', id='related-posts')
            if related_div:
                related_div.decompose()
            
            # Fallback cleanup
            for h3 in soup.find_all('h3'):
                if h3.get_text().strip() == "推荐阅读":
                    parent = h3.find_parent('div')
                    if parent: parent.decompose()

            # === 2. Inject New Elements (注入新元素) ===

            # A. Layout Sync (Common for all types)
            if self.header_html:
                if soup.body: soup.body.insert(0, self.header_html)
            if self.footer_html:
                if soup.body: soup.body.append(self.footer_html)

            # B. Breadcrumbs
            main = soup.find('main') or soup.find('article')
            if main:
                bread_html = self.generate_breadcrumb_html(page['title'], page_type)
                bread_soup = BeautifulSoup(bread_html, 'html.parser')
                main.insert(0, bread_soup)

            # C. Schema Injection
            new_schema = soup.new_tag('script', type='application/ld+json')
            new_schema.string = self.generate_schema(page)
            if soup.head: soup.head.append(new_schema)

            # D. Visual Related Posts (ONLY for Articles)
            if page_type == 'article':
                recs = self.get_related_posts(page, limit=2)
                if recs:
                    rec_items_html = ""
                    for r in recs:
                        rec_items_html += f'''
                        <a class="block group" href="{r['url']}">
                            <div class="bg-white/5 border border-white/10 rounded-xl p-5 hover:bg-white/10 hover:border-violet-500/30 transition-all h-full">
                                <h4 class="text-slate-200 font-bold mb-2 group-hover:text-violet-300 transition-colors line-clamp-1">
                                    {r['title']}
                                </h4>
                                <p class="text-xs text-slate-500 line-clamp-2">
                                    {r['desc']} 
                                </p>
                            </div>
                        </a>
                        '''
                    
                    related_html = f'''
                    <div id="related-posts" class="mt-16 pt-10 border-t border-white/5">
                        <h3 class="text-xl font-bold text-white mb-6">推荐阅读</h3>
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-6 not-prose">
                            {rec_items_html}
                        </div>
                    </div>
                    '''
                    
                    target_container = soup.find('article')
                    if target_container:
                        target_container.append(BeautifulSoup(related_html, 'html.parser'))
                    elif main:
                        main.append(BeautifulSoup(related_html, 'html.parser'))
            
            # For Type 'page', we intentionally DO NOT add related posts (and we already cleaned them)

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(str(soup))
            self.log(f"✅ 已处理 [{page_type.upper()}]: {file_path.name}")

    def update_home_page(self):
        """Update index.html with latest articles"""
        self.log("更新首页...")
        source_path = self.root_dir / SOURCE_FILE
        if not source_path.exists(): return
        
        with open(source_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')
        
        blog_section = soup.find(id='blog')
        if not blog_section:
            self.log("警告: 首页未找到 id='blog' 的区域")
            return
            
        grid = blog_section.find('div', class_=re.compile(r'grid'))
        if grid:
            grid.clear()
            # Filter only articles for home page
            articles = [p for p in self.pages if p['type'] == 'article']
            for page in articles[:3]:
                card_html = self.generate_card_html(page)
                grid.append(BeautifulSoup(card_html, 'html.parser'))
                
            with open(source_path, 'w', encoding='utf-8') as f:
                f.write(str(soup))
            self.log("首页最新文章已更新")
            
    def update_blog_index(self):
        """Update blog/index.html with ALL articles"""
        self.log("更新聚合页...")
        index_path = self.root_dir / BLOG_DIR / "index.html"
        if not index_path.exists():
            self.log(f"聚合页 {index_path} 不存在")
            return

        with open(index_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')

        # === Layout Sync (Header/Footer) ===
        # Remove Header
        if soup.body:
            first_nav = soup.body.find('nav', recursive=False)
            if not first_nav:
                    first_nav = soup.body.find('header', recursive=False)
            if first_nav:
                first_nav.decompose()

        # Remove Footer
        if soup.body:
            footer_tag = soup.body.find('footer', recursive=False)
            if footer_tag:
                footer_tag.decompose()

        # Inject New Header/Footer
        if self.header_html:
            if soup.body: soup.body.insert(0, self.header_html)
        if self.footer_html:
            if soup.body: soup.body.append(self.footer_html)
            
        # Find grid
        grid = soup.find('div', class_=re.compile(r'grid-cols-1.*lg:grid-cols-3'))
        if not grid:
            grids = soup.find_all('div', class_=re.compile(r'grid'))
            if grids: grid = grids[-1]
            
        if grid:
            grid.clear()
            articles = [p for p in self.pages if p['type'] == 'article']
            for page in articles:
                card_html = self.generate_card_html(page)
                grid.append(BeautifulSoup(card_html, 'html.parser'))

        # Update Schema
        old_schema = soup.find('script', type='application/ld+json')
        if old_schema: old_schema.decompose()
        
        # Generate CollectionPage Schema
        schema = {
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": "MjMai 资讯中心",
            "description": "探索 Midjourney 的无限可能，掌握最新 AI 绘画技巧与购买攻略。",
            "url": f"{BASE_URL}/blog/",
            "breadcrumb": {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": 1,
                        "name": "首页",
                        "item": BASE_URL
                    },
                    {
                        "@type": "ListItem",
                        "position": 2,
                        "name": "资讯中心",
                        "item": f"{BASE_URL}/blog/"
                    }
                ]
            },
            "mainEntity": {
                "@type": "ItemList",
                "itemListElement": []
            }
        }
        
        articles = [p for p in self.pages if p['type'] == 'article']
        for i, page in enumerate(articles):
            schema["mainEntity"]["itemListElement"].append({
                "@type": "ListItem",
                "position": i + 1,
                "url": f"{BASE_URL}{page['url']}",
                "name": page['h1']
            })
            
        new_schema = soup.new_tag('script', type='application/ld+json')
        new_schema.string = json.dumps(schema, ensure_ascii=False, indent=4)
        if soup.head: soup.head.append(new_schema)
        
        with open(index_path, 'w', encoding='utf-8') as f:
            f.write(str(soup))
        self.log("聚合页已更新")

    def generate_sitemap(self):
        """Generate sitemap.xml"""
        self.log("生成 sitemap.xml...")
        sitemap_path = self.root_dir / "sitemap.xml"
        
        xml_content = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        
        # Add Homepage
        xml_content.append(f'''  <url>
    <loc>{BASE_URL}/</loc>
    <lastmod>{datetime.date.today().isoformat()}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>''')

        # Add Blog Index
        xml_content.append(f'''  <url>
    <loc>{BASE_URL}/blog/</loc>
    <lastmod>{datetime.date.today().isoformat()}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.9</priority>
  </url>''')

        # Add all pages
        for page in self.pages:
            # Adjust priority based on type
            priority = "0.8"
            changefreq = "monthly"
            
            if page['type'] == 'article':
                changefreq = "weekly"
            
            if page['type'] == 'page':
                 priority = "0.8"
                 changefreq = "monthly"
            
            # Ensure full URL
            full_url = f"{BASE_URL}{page['url']}"
            date_str = page['date'].strftime('%Y-%m-%d')
            
            xml_content.append(f'''  <url>
    <loc>{full_url}</loc>
    <lastmod>{date_str}</lastmod>
    <changefreq>{changefreq}</changefreq>
    <priority>{priority}</priority>
  </url>''')
            
        xml_content.append('</urlset>')
        
        with open(sitemap_path, 'w', encoding='utf-8') as f:
            f.write('\\n'.join(xml_content))
            
        self.log(f"✅ Sitemap 已更新: {len(self.pages) + 2} 个链接")

if __name__ == "__main__":
    builder = StaticSiteBuilder()
    builder.load_templates()
    builder.scan_content()
    builder.process_pages() # Renamed from process_articles
    builder.update_home_page()
    builder.update_blog_index()
    builder.generate_sitemap()
    print("\\n🎉 构建完成！页面类型检测已启用 (Article/Page)。")
