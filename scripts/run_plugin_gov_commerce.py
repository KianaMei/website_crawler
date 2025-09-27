from plugins.gov_commerce import handler, Input


def main() -> None:
    class Args:
        pass

    args = Args()
    args.input = Input(url="https://www.mofcom.gov.cn/")
    resp = handler(args)
    lines = []
    lines.append(f"status: {resp.status} count: {len(resp.news_list or [])}")
    if resp.news_list:
        for idx, n in enumerate(resp.news_list[:5], start=1):
            lines.append(f"{idx} {n.title} {n.url}")
    with open("tmp_gov_commerce_plugin.log", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()


