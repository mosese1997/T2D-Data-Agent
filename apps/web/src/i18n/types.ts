/** 字典类型：key 为稳定的英文语义键，值为含 {name} 占位符的文案 */
export type Dictionary = Record<string, string>;

/** 插值参数 */
export type TranslateParams = Record<string, string | number>;
