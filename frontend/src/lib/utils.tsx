import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { ExternalLink } from 'lucide-react';

export function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs));
}

// Helper to render text with markdown links and auto-linked URLs
export const renderTextContent = (content: string) => {
    // Regex to match markdown links OR raw URLs
    // Group 1: Markdown Label, Group 2: Markdown URL, Group 3: Raw URL
    const regex = /\[([^\]]+)\]\(([^)]+)\)|(https?:\/\/[^\s]+)/g;

    const parts = [];
    let lastIndex = 0;
    let match;

    while ((match = regex.exec(content)) !== null) {
        // Add text before the match
        if (match.index > lastIndex) {
            parts.push(content.substring(lastIndex, match.index));
        }

        if (match[3]) {
            // Raw URL Case
            const url = match[3];
            parts.push(
                <a
                    key={match.index}
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-400 underline hover:text-blue-300 break-all"
                >
                    {url} <ExternalLink className="inline h-3 w-3 mb-1" />
                </a>
            );
        } else {
            // Markdown Link Case
            parts.push(
                <a
                    key={match.index}
                    href={match[2]}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-white underline decoration-zinc-600 underline-offset-4 hover:decoration-white hover:bg-white hover:text-black transition-all"
                >
                    {match[1]} <ExternalLink className="inline h-3 w-3 mb-1" />
                </a>
            );
        }

        lastIndex = regex.lastIndex;
    }

    if (lastIndex < content.length) {
        parts.push(content.substring(lastIndex));
    }

    if (parts.length === 0) return <div className="whitespace-pre-wrap">{content}</div>;
    return <div className="whitespace-pre-wrap">{parts}</div>;
};
