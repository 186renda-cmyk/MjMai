import os
from pathlib import Path
from bs4 import BeautifulSoup

# 配置
TARGET_EXT = ['.html']
IGNORE_DIRS = ['.git', 'node_modules', '__pycache__']
# 你的 Base URL (可选，用于处理 absolute URLs 如果需要)
BASE_URL = "https://mjmai.top"

def fix_all_internal_links(root_dir='.'):
    root_path = Path(root_dir).resolve()
    count = 0
    
    print(f"🚀 开始全站链接绝对化修复: {root_path}")

    for file_path in root_path.rglob('*'):
        if file_path.is_dir() or file_path.suffix not in TARGET_EXT:
            continue
        if any(part in str(file_path) for part in IGNORE_DIRS):
            continue
            
        # 计算当前文件相对于根目录的“深度前缀”
        # 例如: 文件在 /blog/a.html，相对路径链接 'b.html' -> 应该变成 '/blog/b'
        rel_dir = file_path.parent.relative_to(root_path)
        base_prefix = f"/{rel_dir.as_posix()}/" if str(rel_dir) != "." else "/"
        
        # 修正：如果 base_prefix 是 "//" (根目录情况), 改为 "/"
        if base_prefix == "//": base_prefix = "/"

        with open(file_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')
        
        modified = False
        
        for a in soup.find_all('a', href=True):
            href = a['href']
            
            # 1. 跳过已经是绝对路径、外部链接或锚点
            if href.startswith(('/', 'http', '#', 'mailto:', 'tel:', 'javascript:')):
                continue
            
            # 2. 计算绝对路径
            # 逻辑：当前目录前缀 + 相对链接
            new_href = base_prefix + href
            
            # 3. 清理 .html 后缀 (Cloudflare Clean URL)
            if new_href.endswith('.html'):
                new_href = new_href[:-5]
            
            # 4. 清理 index 结尾
            if new_href.endswith('/index'):
                new_href = new_href[:-6] + '/'

            # 5. 去重多余的斜杠 (例如 /blog//abc -> /blog/abc)
            new_href = new_href.replace('//', '/')
            
            if href != new_href:
                # print(f"   [修复] {file_path.name}: {href} -> {new_href}")
                a['href'] = new_href
                modified = True

        if modified:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(str(soup))
            count += 1
            print(f"✅ 已修正文件: {file_path.name}")

    print(f"\n🎉 修复完成！共处理了 {count} 个文件。")

if __name__ == "__main__":
    fix_all_internal_links()