/* eslint-disable @typescript-eslint/no-explicit-any */

export interface SettingsModalProps {
    isOpen: boolean;
    onClose: () => void;
    onSave: (name: string, model: string, mode: string, keys: any) => void | Promise<void>;
    credentials?: any;
    showBrowser: boolean;
    onToggleBrowser: (val: boolean) => void;
}

export type Tab = 'general' | 'models' | 'workspace' | 'database' | 'memory' | 'agents' | 'datalab' | 'custom_tools' | 'personal_details' | 'mcp_servers';

// Tool Group Definitions for UI
export const CAPABILITIES = [
    {
        id: 'gmail',
        label: 'Gmail',
        description: 'Read, draft, and send emails.',
        tools: ['list_emails', 'read_email', 'get_recent_emails_content', 'draft_email', 'send_email']
    },
    {
        id: 'drive',
        label: 'Google Drive',
        description: 'List and read files from Drive.',
        tools: ['list_files', 'read_file_content', 'create_file']
    },
    {
        id: 'calendar',
        label: 'Calendar',
        description: 'View and schedule events.',
        tools: ['list_upcoming_events', 'create_event']
    },
    {
        id: 'local_files',
        label: 'Local Files',
        description: 'Access files on your computer.',
        tools: ['list_local_files', 'read_local_file']
    },
    {
        id: 'browser',
        label: 'Browser Automation',
        description: 'Visit websites and read content.',
        tools: ['visit_page']
    },
    {
        id: 'web_search',
        label: 'Web Search',
        description: 'Search the internet for info.',
        tools: ['search_web']
    },
    {
        id: 'maps',
        label: 'Google Maps',
        description: 'Distance, duration, and directions link between two points.',
        tools: ['get_map_details']
    },
    {
        id: 'sql',
        label: 'SQL Database',
        description: 'Query business database (Tables, SQL).',
        tools: ['list_tables', 'get_table_schema', 'run_sql_query']
    },
    {
        id: 'datetime',
        label: 'Date & Time',
        description: 'Get current and future dates with natural language.',
        tools: ['get_datetime']
    },
    {
        id: 'personal_details',
        label: 'Personal Details',
        description: 'Get saved personal info (name, phone, address).',
        tools: ['get_personal_details']
    },
    {
        id: 'pdf_parser',
        label: 'PDF Parser',
        description: 'Parse content from PDF files via URL.',
        tools: ['parse_pdf']
    },
    {
        id: 'xlsx_parser',
        label: 'Excel Parser',
        description: 'Parse content from Excel (XLSX) files via URL.',
        tools: ['parse_xlsx']
    }
];
