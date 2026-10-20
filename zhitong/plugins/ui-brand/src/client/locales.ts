/** 智通数工AI brand copy. The product and model names are the same in every locale (zhitong/README.md §2). */

/** Chinese brand dictionary. */
export const zh = {
  /** Product name shown by the wordmark. */
  name: '智通数工AI',
  /** Display name of the recommended model (`deepseek-flash` on the official DeepSeek routes). */
  recommendedModel: 'DeepSeek V4.1 Flash',
  /** Badge beside the recommended model. */
  recommendedBadge: '官方推荐',
}

/** English brand dictionary; the product name is not translated. */
export const en: Record<BrandKey, string> = {
  name: '智通数工AI',
  recommendedModel: 'DeepSeek V4.1 Flash',
  recommendedBadge: 'Recommended',
}

/** Keys of the brand namespace. */
export type BrandKey = keyof typeof zh
