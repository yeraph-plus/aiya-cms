const escapedCharacters: Record<string, string> = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
};

const namedEntities: Record<string, string> = {
    amp: '&',
    apos: "'",
    colon: ':',
    gt: '>',
    lt: '<',
    newline: '\n',
    period: '.',
    quot: '"',
    sol: '/',
    tab: '\t'
};

const markdownPunctuation = /[!"#$%&'()*+,\-./:;<=>?@[\\\]^_`{|}~]/u;

export interface MarkdownRenderOptions {
    allowImages?: boolean;
}

export function escapeHtml(value: string): string {
    return value.replace(/[&<>"']/gu, (character) => escapedCharacters[character] ?? character);
}

function decodeHtmlEntities(value: string): string {
    return value.replace(/&(?:#(\d+)|#x([\da-f]+)|([a-z][\da-z]+));/giu, (match, decimal, hexadecimal, name) => {
        if (name) return namedEntities[name.toLowerCase()] ?? match;

        const codePoint = Number.parseInt(decimal ?? hexadecimal, decimal ? 10 : 16);
        if (!Number.isSafeInteger(codePoint) || codePoint <= 0 || codePoint > 0x10ffff) return match;

        try {
            return String.fromCodePoint(codePoint);
        } catch {
            return match;
        }
    });
}

function decodeUrl(value: string): string {
    let decoded = decodeHtmlEntities(value);
    for (let attempt = 0; attempt < 3; attempt += 1) {
        try {
            const next = decodeURIComponent(decoded);
            if (next === decoded) break;
            decoded = next;
        } catch {
            break;
        }
    }
    return decoded;
}

function hasControlCharacter(value: string): boolean {
    return [...value].some((character) => {
        const codePoint = character.codePointAt(0) ?? 0;
        return codePoint <= 0x20 || codePoint === 0x7f;
    });
}

function removeControlCharacters(value: string): string {
    return [...value]
        .filter((character) => {
            const codePoint = character.codePointAt(0) ?? 0;
            return codePoint > 0x20 && codePoint !== 0x7f;
        })
        .join('');
}

export function sanitizeUrl(value: string | null | undefined): string | null {
    if (!value) return null;

    const candidate = value.trim();
    const decoded = decodeUrl(candidate);
    if (!decoded || hasControlCharacter(decoded) || decoded.includes('\\')) return null;

    const compact = removeControlCharacters(decoded).toLowerCase();
    const scheme = compact.match(/^([a-z][a-z\d+.-]*):/u)?.[1];
    if (scheme && !['http', 'https', 'mailto'].includes(scheme)) return null;
    if (!scheme && candidate.startsWith('//')) return null;

    try {
        const parsed = new URL(candidate, 'https://aiya.invalid');
        if (scheme && parsed.protocol !== `${scheme}:`) return null;
        if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:' && parsed.protocol !== 'mailto:') {
            if (scheme || candidate.startsWith('//')) return null;
        }
    } catch {
        return null;
    }

    return candidate;
}

export function isSafeUrl(value: string | null | undefined): boolean {
    return sanitizeUrl(value) !== null;
}

function isEscaped(value: string, index: number): boolean {
    let slashCount = 0;
    for (let cursor = index - 1; cursor >= 0 && value[cursor] === '\\'; cursor -= 1) slashCount += 1;
    return slashCount % 2 === 1;
}

function findClosing(value: string, marker: string, start: number): number {
    let cursor = start;
    while (cursor < value.length) {
        const found = value.indexOf(marker, cursor);
        if (found === -1) return -1;
        if (!isEscaped(value, found)) return found;
        cursor = found + marker.length;
    }
    return -1;
}

function findLinkEnd(value: string, start: number): number {
    let depth = 0;
    for (let cursor = start; cursor < value.length; cursor += 1) {
        if (isEscaped(value, cursor)) continue;
        if (value[cursor] === '(') depth += 1;
        if (value[cursor] !== ')') continue;
        if (depth === 0) return cursor;
        depth -= 1;
    }
    return -1;
}

function parseLinkDestination(value: string): { url: string; title?: string } | null {
    const input = value.trim();
    if (!input) return null;

    let url = input;
    let remainder = '';
    if (input.startsWith('<')) {
        const closing = input.indexOf('>');
        if (closing < 0) return null;
        url = input.slice(1, closing);
        remainder = input.slice(closing + 1).trim();
    } else {
        const separator = input.search(/\s/u);
        if (separator >= 0) {
            url = input.slice(0, separator);
            remainder = input.slice(separator).trim();
        }
    }

    if (!url) return null;
    if (!remainder) return { url };
    const title = remainder.match(/^["']([^"']*)["']$/u)?.[1];
    return title === undefined ? null : { url, title };
}

function renderInline(source: string, options: MarkdownRenderOptions, depth = 0): string {
    if (depth > 8) return escapeHtml(source);

    let output = '';
    let textStart = 0;
    const appendText = (value: string) => {
        output += escapeHtml(value).replace(/ {2,}\n/gu, '<br>\n');
    };
    const flushText = (end: number) => {
        if (end > textStart) appendText(source.slice(textStart, end));
    };

    for (let cursor = 0; cursor < source.length; cursor += 1) {
        const character = source[cursor] ?? '';
        const nextCharacter = source[cursor + 1];

        if (character === '\\' && nextCharacter && markdownPunctuation.test(nextCharacter)) {
            flushText(cursor);
            output += escapeHtml(nextCharacter);
            cursor += 1;
            textStart = cursor + 1;
            continue;
        }

        if (character === '`') {
            const marker = source.startsWith('```', cursor) ? '```' : '`';
            const closing = findClosing(source, marker, cursor + marker.length);
            if (closing >= 0) {
                flushText(cursor);
                const code = source
                    .slice(cursor + marker.length, closing)
                    .replace(/\s+/gu, ' ')
                    .trim();
                output += `<code>${escapeHtml(code)}</code>`;
                cursor = closing + marker.length - 1;
                textStart = cursor + 1;
            }
            continue;
        }

        const isImage = character === '!' && source[cursor + 1] === '[';
        const isLink = character === '[';
        if (isImage || isLink) {
            const labelStart = cursor + (isImage ? 2 : 1);
            const destinationStart = source.indexOf('](', labelStart);
            if (destinationStart >= labelStart) {
                const closing = findLinkEnd(source, destinationStart + 2);
                if (closing >= 0) {
                    const label = source.slice(labelStart, destinationStart);
                    const destination = parseLinkDestination(source.slice(destinationStart + 2, closing));
                    if (destination) {
                        flushText(cursor);
                        const safeUrl = sanitizeUrl(destination.url);
                        if (isImage && options.allowImages !== false) {
                            if (safeUrl) {
                                const title = destination.title ? ` title="${escapeHtml(destination.title)}"` : '';
                                output += `<img src="${escapeHtml(safeUrl)}" alt="${escapeHtml(label)}" loading="lazy" decoding="async"${title}>`;
                            } else {
                                output += renderInline(label, options, depth + 1);
                            }
                        } else if (safeUrl) {
                            const title = destination.title ? ` title="${escapeHtml(destination.title)}"` : '';
                            output += `<a href="${escapeHtml(safeUrl)}"${title}>${renderInline(label, options, depth + 1)}</a>`;
                        } else {
                            output += renderInline(label, options, depth + 1);
                        }
                        cursor = closing;
                        textStart = cursor + 1;
                    }
                }
            }
            continue;
        }

        let marker: '**' | '__' | '~~' | '*' | '_' | undefined;
        if (source.startsWith('**', cursor)) marker = '**';
        else if (source.startsWith('__', cursor)) marker = '__';
        else if (source.startsWith('~~', cursor)) marker = '~~';
        else if (character === '*' || character === '_') marker = character;

        if (marker) {
            const next = source[cursor + marker.length];
            if (next && !/\s/u.test(next) && !(marker === '_' && /\w/u.test(source[cursor - 1] ?? ''))) {
                const closing = findClosing(source, marker, cursor + marker.length);
                if (closing > cursor + marker.length) {
                    flushText(cursor);
                    const inner = renderInline(source.slice(cursor + marker.length, closing), options, depth + 1);
                    const tag = marker === '~~' ? 'del' : marker.length === 1 ? 'em' : 'strong';
                    output += `<${tag}>${inner}</${tag}>`;
                    cursor = closing + marker.length - 1;
                    textStart = cursor + 1;
                }
            }
        }
    }

    flushText(source.length);
    return output;
}

function isBlockStart(line: string): boolean {
    return /^(?: {0,3}(?:#{1,6}\s|```|~~~|>\s?|[-+*]\s+|\d+[.)]\s+)| {0,3}(?:[-*_])(?:\s*[-*_]){2,}\s*$)/u.test(line);
}

function renderList(lines: string[], start: number, options: MarkdownRenderOptions): { html: string; next: number } {
    const first = (lines[start] ?? '').match(/^ {0,3}([-+*]|\d+[.)])\s+(.+)$/u);
    if (!first) return { html: '', next: start + 1 };

    const firstMarker = first[1] ?? '';
    const firstText = first[2] ?? '';
    const ordered = /^\d/u.test(firstMarker);
    const items: string[] = [];
    let cursor = start;
    while (cursor < lines.length) {
        const match = (lines[cursor] ?? '').match(/^ {0,3}([-+*]|\d+[.)])\s+(.+)$/u);
        const marker = match?.[1] ?? '';
        const text = match?.[2] ?? '';
        if (!match || /^\d/u.test(marker) !== ordered) break;
        items.push(`<li>${renderInline(text, options)}</li>`);
        cursor += 1;
    }

    if (items.length === 0) items.push(`<li>${renderInline(firstText, options)}</li>`);

    return { html: `<${ordered ? 'ol' : 'ul'}>\n${items.join('\n')}\n</${ordered ? 'ol' : 'ul'}>`, next: cursor };
}

export function renderMarkdown(source: string | null | undefined, options: MarkdownRenderOptions = {}): string {
    if (!source) return '';

    const lines = source.replace(/\r\n?/gu, '\n').split('\n');
    const blocks: string[] = [];
    let cursor = 0;

    while (cursor < lines.length) {
        const line = lines[cursor] ?? '';
        if (!line.trim()) {
            cursor += 1;
            continue;
        }

        const fence = line.match(/^ {0,3}(`{3,}|~{3,})\s*([^\s]*)?.*$/u);
        if (fence) {
            const markerText = fence[1] ?? '```';
            const marker = markerText[0] ?? '`';
            const markerLength = markerText.length;
            const codeLines: string[] = [];
            cursor += 1;
            while (
                cursor < lines.length &&
                !new RegExp(`^ {0,3}${marker}{${markerLength},}\\s*$`, 'u').test(lines[cursor] ?? '')
            ) {
                codeLines.push(lines[cursor] ?? '');
                cursor += 1;
            }
            if (cursor < lines.length) cursor += 1;
            const languageValue = fence[2] ?? '';
            const language = languageValue && /^[a-z\d_+-]{1,32}$/iu.test(languageValue) ? languageValue : '';
            const className = language ? ` class="language-${escapeHtml(language)}"` : '';
            blocks.push(`<pre><code${className}>${escapeHtml(codeLines.join('\n'))}</code></pre>`);
            continue;
        }

        const heading = line.match(/^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$/u);
        if (heading) {
            const headingMarker = heading[1] ?? '#';
            const headingText = heading[2] ?? '';
            const level = headingMarker.length;
            blocks.push(`<h${level}>${renderInline(headingText, options)}</h${level}>`);
            cursor += 1;
            continue;
        }

        if (/^ {0,3}(?:\*\s*){3,}$|^ {0,3}(?:-\s*){3,}$|^ {0,3}(?:_\s*){3,}$/u.test(line)) {
            blocks.push('<hr>');
            cursor += 1;
            continue;
        }

        if (/^ {0,3}>/u.test(line)) {
            const quoteLines: string[] = [];
            while (cursor < lines.length && /^ {0,3}>/u.test(lines[cursor] ?? '')) {
                quoteLines.push((lines[cursor] ?? '').replace(/^ {0,3}>\s?/u, ''));
                cursor += 1;
            }
            blocks.push(`<blockquote>\n${renderMarkdown(quoteLines.join('\n'), options)}\n</blockquote>`);
            continue;
        }

        if (/^ {0,3}(?:[-+*]|\d+[.)])\s+/u.test(line)) {
            const list = renderList(lines, cursor, options);
            blocks.push(list.html);
            cursor = list.next;
            continue;
        }

        const paragraph: string[] = [line];
        cursor += 1;
        while (cursor < lines.length && (lines[cursor] ?? '').trim() && !isBlockStart(lines[cursor] ?? '')) {
            paragraph.push(lines[cursor] ?? '');
            cursor += 1;
        }
        blocks.push(`<p>${renderInline(paragraph.join('\n'), options)}</p>`);
    }

    return blocks.join('\n');
}

export function markdownToText(source: string | null | undefined): string {
    if (!source) return '';
    const rendered = renderMarkdown(source, { allowImages: false })
        .replace(/<img\b[^>]*>/giu, ' ')
        .replace(/<[^>]+>/gu, ' ');
    return decodeHtmlEntities(rendered).replace(/\s+/gu, ' ').trim();
}
