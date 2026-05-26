const SOURCE_ICON_FALLBACKS = {
    weibo: '🔥',
    zhihu: '💡',
    bilibili: '📺',
    v2ex: '💻',
    hackernews: '🔶',
    juejin: '💎',
    linuxdo: '🐧',
    nodeseek: '🌐',
    sspai: '📱',
    douban_movie: '🎬',
    douban_book: '📚',
    zaobao: '🌏',
    thepaper: '📰'
}

export const isImageIcon = (icon) => {
    return typeof icon === 'string' && /^(https?:\/\/|data:image\/|\/icons\/)/.test(icon)
}

export const getSourceFallbackIcon = (sourceId, sourceName = '') => {
    if (SOURCE_ICON_FALLBACKS[sourceId]) return SOURCE_ICON_FALLBACKS[sourceId]
    if (sourceName.includes('电影') || sourceName.includes('热映')) return '🎬'
    if (sourceName.includes('书')) return '📚'
    if (sourceName.includes('新闻') || sourceName.includes('早报')) return '📰'
    if (sourceName.includes('技术') || sourceName.includes('Hacker')) return '💻'
    return '📰'
}
