import { fetchJSON, jsonBody } from '$lib/apis';

export type MemoryScope = 'user' | 'workspace';
export type MemoryOperation = {
	action: 'add' | 'replace' | 'remove';
	content?: string;
	old_text?: string;
};

export type MemorySettings = {
	enabled: boolean;
	tool_enabled: boolean;
	background_review_enabled: boolean;
	review_interval_turns: number;
	user_char_limit: number;
	workspace_char_limit: number;
};

export type MemoryState = {
	settings: MemorySettings;
	user: { entries: string[]; usage: string; path: string };
	workspace: { entries: string[]; usage: string; path: string };
};

export const getMemory = (workspace: string) =>
	fetchJSON<MemoryState>(`/api/memory?workspace=${encodeURIComponent(workspace || '')}`);

export const updateMemorySettings = (settings: Partial<MemorySettings>) =>
	fetchJSON<{ settings: MemorySettings }>('/api/memory/config', {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ settings })
	});

export const updateMemory = (
	scope: MemoryScope,
	workspace: string,
	operations: MemoryOperation[]
) =>
	fetchJSON('/api/memory/update', jsonBody({ scope, workspace, operations }));
