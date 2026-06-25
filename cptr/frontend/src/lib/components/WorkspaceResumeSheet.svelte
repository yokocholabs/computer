<script lang="ts">
	import {
		activeWorkspace,
		setActiveTab,
		gitReviewOpen,
		openPreviewTab,
		type Tab
	} from '$lib/stores';
	import { systemEvents } from '$lib/stores/systemEvents.svelte';
	import { gitStatusStore } from '$lib/stores/gitStatus.svelte';
	import Icon from './Icon.svelte';

	interface Props {
		onclose: () => void;
	}

	let { onclose }: Props = $props();

	const tabs = $derived($activeWorkspace?.groups.flatMap((group) => group.tabs) ?? []);
	const nonFileTabs = $derived(
		tabs.filter(
			(tab) => ['terminal', 'chat', 'preview', 'file'].includes(tab.type) && !tab.permanent
		)
	);
	const terminalTabs = $derived(tabs.filter((tab) => tab.type === 'terminal'));
	const chatTabs = $derived(tabs.filter((tab) => tab.type === 'chat'));
	const previewTabs = $derived(tabs.filter((tab) => tab.type === 'preview' && tab.port));
	const gitStatus = $derived(gitStatusStore.status);
	const changedFiles = $derived(gitStatus?.files?.length ?? 0);
	const livePorts = $derived(
		systemEvents.ports.filter((port) =>
			tabs.some((tab) => tab.type === 'terminal' && tab.sessionId === port.session_id)
		)
	);
	const hasResumeItems = $derived(
		terminalTabs.length > 0 ||
			chatTabs.length > 0 ||
			previewTabs.length > 0 ||
			livePorts.length > 0 ||
			changedFiles > 0 ||
			nonFileTabs.length > 1
	);

	function activateTab(tab: Tab) {
		const group = $activeWorkspace?.groups.find((g) => g.tabs.some((t) => t.id === tab.id));
		if (!group) return;
		setActiveTab(tab.id, group.id);
		onclose();
	}

	function openGit() {
		gitReviewOpen.set(true);
		onclose();
	}

	function openPort(port: number) {
		openPreviewTab(port);
		onclose();
	}
</script>

{#if hasResumeItems}
	<section class="resume-sheet md:hidden" aria-label="Workspace resume">
		<div class="mb-1.5 flex items-baseline justify-between gap-3">
			<div class="min-w-0">
				<h2 class="truncate text-xs font-medium text-gray-800 dark:text-gray-200">
					{$activeWorkspace?.name}
				</h2>
				<p class="truncate font-mono text-[10px] text-gray-400 dark:text-gray-600">
					{$activeWorkspace?.path}
				</p>
			</div>
			<button
				class="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
				onclick={onclose}
				aria-label="Dismiss resume"
			>
				<Icon name="xmark" size={11} />
			</button>
		</div>

		<div class="space-y-px">
			{#if changedFiles > 0}
				<button class="resume-row" onclick={openGit}>
					<Icon name="git-diff" size={14} />
					<span class="min-w-0 flex-1 truncate">{changedFiles} changed files</span>
					<span class="resume-meta">{gitStatus?.branch}</span>
				</button>
			{/if}

			{#each livePorts as port (port.port)}
				<button class="resume-row" onclick={() => openPort(port.port)}>
					<Icon name="monitor" size={14} />
					<span class="min-w-0 flex-1 truncate">localhost:{port.port}</span>
					<span class="resume-meta">{port.process}</span>
				</button>
			{/each}

			{#each terminalTabs as tab (tab.id)}
				<button class="resume-row" onclick={() => activateTab(tab)}>
					<Icon name="terminal" size={14} />
					<span class="min-w-0 flex-1 truncate">{tab.label || 'Terminal'}</span>
					<span class="resume-meta">{tab.sessionId ? 'running' : 'starting'}</span>
				</button>
			{/each}

			{#each chatTabs as tab (tab.id)}
				<button class="resume-row" onclick={() => activateTab(tab)}>
					<Icon name="chat-bubble" size={14} />
					<span class="min-w-0 flex-1 truncate">{tab.label || 'Chat'}</span>
					<span class="resume-meta">chat</span>
				</button>
			{/each}

			{#each previewTabs as tab (tab.id)}
				<button class="resume-row" onclick={() => activateTab(tab)}>
					<Icon name="monitor" size={14} />
					<span class="min-w-0 flex-1 truncate">{tab.label || `localhost:${tab.port}`}</span>
					<span class="resume-meta">preview</span>
				</button>
			{/each}
		</div>
	</section>
{/if}

<style>
	@reference "../../app.css";

	.resume-sheet {
		position: fixed;
		left: 8px;
		right: 8px;
		bottom: calc(8px + env(safe-area-inset-bottom, 0px));
		z-index: 90;
		max-height: min(44dvh, 280px);
		overflow-y: auto;
		border: 1px solid var(--color-gray-200);
		border-radius: 12px;
		background: white;
		padding: 7px;
		box-shadow: 0 8px 28px rgba(0, 0, 0, 0.12);
	}

	:global(.dark) .resume-sheet {
		border-color: rgba(255, 255, 255, 0.08);
		background: #050505;
		box-shadow: 0 8px 28px rgba(0, 0, 0, 0.45);
	}

	.resume-row {
		display: flex;
		width: 100%;
		align-items: center;
		gap: 7px;
		border-radius: 7px;
		padding: 5px 6px;
		text-align: left;
		font-size: 11px;
		color: var(--color-gray-700);
		transition:
			background 0.1s,
			color 0.1s;
	}

	.resume-row:hover {
		background: var(--color-gray-100);
		color: var(--color-gray-950);
	}

	:global(.dark) .resume-row {
		color: var(--color-gray-300);
	}

	:global(.dark) .resume-row:hover {
		background: rgba(255, 255, 255, 0.06);
		color: white;
	}

	.resume-meta {
		min-width: 0;
		max-width: 42%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-family: var(--font-mono);
		font-size: 9px;
		color: var(--color-gray-400);
	}

	:global(.dark) .resume-meta {
		color: var(--color-gray-600);
	}
</style>
