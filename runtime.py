class Args:
    # 允许在类型注解中使用 Args[T]
    def __class_getitem__(cls, item):  # type: ignore[no-redef]
        return cls


