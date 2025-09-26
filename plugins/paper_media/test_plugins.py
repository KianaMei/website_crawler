"""
独立纸媒插件测试脚本

用于测试每个拆分后的纸媒插件是否能独立运行
"""

import sys
import os
import logging
from typing import Type

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


class MockArgs:
    """模拟Args对象用于测试"""
    def __init__(self, input_data=None):
        self.input = input_data or {}
        self.logger = logging.getLogger(__name__)


def test_plugin(plugin_name: str, plugin_module):
    """测试单个插件"""
    print(f"\n{'='*50}")
    print(f"测试插件: {plugin_name}")
    print(f"{'='*50}")
    
    # 检查是否有handler函数
    if not hasattr(plugin_module, 'handler'):
        print(f"❌ {plugin_name} 缺少 handler 函数")
        return False
    
    # 检查是否有Metadata
    if not hasattr(plugin_module, 'Metadata'):
        print(f"❌ {plugin_name} 缺少 Metadata")
        return False
    
    print(f"✅ {plugin_name} 结构检查通过")
    print(f"描述: {plugin_module.Metadata.get('description', 'N/A')}")
    
    # 测试运行
    try:
        args = MockArgs({
            'max_items': 3,  # 少量测试数据
            'date': None,
            'since_days': 3
        })
        
        result = plugin_module.handler(args)
        
        print(f"状态: {result.status}")
        if result.news_list:
            print(f"获取新闻数量: {len(result.news_list)}")
            for i, news in enumerate(result.news_list[:2]):  # 只显示前2条
                print(f"  {i+1}. {news.title[:50]}...")
        else:
            print(f"错误码: {result.err_code}")
            print(f"错误信息: {result.err_info}")
        
        return True
        
    except Exception as e:
        print(f"❌ {plugin_name} 运行异常: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主测试函数"""
    print("开始测试独立纸媒插件...")
    
    # 插件列表
    plugins = [
        ('人民日报', 'plugins.paper_media.peopledaily'),
        ('光明日报', 'plugins.paper_media.guangming'),
        ('经济日报', 'plugins.paper_media.economic'),
        ('新华每日电讯', 'plugins.paper_media.xinhua'),
        ('经济参考报', 'plugins.paper_media.jjckb'),
        ('求是', 'plugins.paper_media.qiushi'),
    ]
    
    success_count = 0
    total_count = len(plugins)
    
    for name, module_path in plugins:
        try:
            module = __import__(module_path, fromlist=[''])
            if test_plugin(name, module):
                success_count += 1
        except ImportError as e:
            print(f"❌ 无法导入 {name}: {e}")
        except Exception as e:
            print(f"❌ {name} 测试失败: {e}")
    
    print(f"\n{'='*50}")
    print(f"测试完成: {success_count}/{total_count} 个插件通过测试")
    print(f"{'='*50}")
    
    return success_count == total_count


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)