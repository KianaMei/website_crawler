from enum import Enum


class NDRCCategory(str, Enum):
    """国家发改委政策分类枚举"""
    FZGGWL = "fzggwl"  # 发展改革委（综合）
    GHXWJ = "ghxwj"    # 规范性文件
    GHWB = "ghwb"      # 规划文本
    GG = "gg"          # 公告
    TZ = "tz"          # 通知


class ACFICChannel(str, Enum):
    """全联政策频道枚举"""
    ZY = "zy"      # 中央
    BW = "bw"      # 部委
    DF = "df"      # 地方
    QGGSL = "qggsl"  # 全联自有
    JD = "jd"      # 解读


class CFLPChannel(str, Enum):
    """中物联频道枚举"""
    ZCFG = "zcfg"  # 政策法规
    ZIXUN = "zixun"  # 资讯