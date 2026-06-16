/**
 * Audio state: voice memos feature flag, transcription toggle, recording quality, and modal visibility.
 */
import { writable } from 'svelte/store';
import { fetchJSON } from '$lib/apis';

export type RecordingQuality = 'high' | 'medium' | 'low';

export const QUALITY_BITRATES: Record<RecordingQuality, number> = {
	high: 128000,
	medium: 64000,
	low: 32000
};

export const voiceMemosEnabled = writable<boolean>(false);
export const transcribeEnabled = writable<boolean>(true);
export const sttConfigured = writable<boolean>(false);
export const recordingQuality = writable<RecordingQuality>('high');
export const showVoiceMemo = writable<boolean>(false);
export const ttsEnabled = writable<boolean>(false);
export const ttsConfigured = writable<boolean>(false);
export const ttsVoice = writable<string>('alloy');
export const ttsFormat = writable<string>('mp3');
export const voiceModeEnabled = writable<boolean>(false);
export const voiceModeSttMode = writable<'browser' | 'provider'>('browser');
export const ttsPlaybackEnabled = writable<boolean>(
	typeof localStorage !== 'undefined' ? localStorage.getItem('ttsPlaybackEnabled') === 'true' : false
);

const SILENT_WAV =
	'data:audio/wav;base64,UklGRigAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQQAAAAAAA==';

let ttsAudioElement: HTMLAudioElement | null = null;
let ttsAudioContext: AudioContext | null = null;
let ttsAudioUnlocked = false;

ttsPlaybackEnabled.subscribe((v) => {
	if (typeof localStorage !== 'undefined') localStorage.setItem('ttsPlaybackEnabled', String(v));
});

export function getTtsAudioElement(): HTMLAudioElement | null {
	if (typeof Audio === 'undefined') return null;
	if (!ttsAudioElement) {
		ttsAudioElement = new Audio();
		ttsAudioElement.preload = 'auto';
		(ttsAudioElement as HTMLAudioElement & { playsInline?: boolean }).playsInline = true;
	}
	return ttsAudioElement;
}

export async function unlockTtsAudioPlayback() {
	if (typeof window === 'undefined') return;

	const unlocks: Promise<unknown>[] = [];
	const AudioContextCtor =
		window.AudioContext || (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
	try {
		if (AudioContextCtor) {
			ttsAudioContext ??= new AudioContextCtor();
			const buffer = ttsAudioContext.createBuffer(1, 1, 22050);
			const source = ttsAudioContext.createBufferSource();
			source.buffer = buffer;
			source.connect(ttsAudioContext.destination);
			source.start(0);
			if (ttsAudioContext.state !== 'running') unlocks.push(ttsAudioContext.resume());
		}
	} catch {}

	const audio = getTtsAudioElement();
	if (audio && !ttsAudioUnlocked) {
		try {
			audio.src = SILENT_WAV;
			audio.volume = 0;
			const started = audio.play();
			unlocks.push(
				Promise.resolve(started)
					.then(() => {
						ttsAudioUnlocked = true;
					})
					.finally(() => {
						audio.pause();
						audio.currentTime = 0;
						audio.removeAttribute('src');
						audio.load();
						audio.volume = 1;
					})
			);
		} catch {}
	}

	await Promise.allSettled(unlocks);
}

export async function refreshAudioState() {
	try {
		const data = await fetchJSON<{
			voice_memos_enabled: boolean;
			transcribe_enabled: boolean;
			stt_configured: boolean;
			recording_quality: string;
			tts_enabled: boolean;
			tts_configured: boolean;
			tts_voice: string;
			tts_format: string;
			voice_mode_stt_mode?: string;
		}>('/api/audio/state');
		voiceMemosEnabled.set(data.voice_memos_enabled === true);
		transcribeEnabled.set(data.transcribe_enabled !== false);
		sttConfigured.set(data.stt_configured === true);
		const q = data.recording_quality;
		if (q === 'medium' || q === 'low') recordingQuality.set(q);
		else recordingQuality.set('high');
		ttsEnabled.set(data.tts_enabled === true);
		ttsConfigured.set(data.tts_configured === true);
		ttsVoice.set(data.tts_voice || 'alloy');
		ttsFormat.set(data.tts_format || 'mp3');
		voiceModeSttMode.set(data.voice_mode_stt_mode === 'provider' ? 'provider' : 'browser');
	} catch {
		voiceMemosEnabled.set(false);
		sttConfigured.set(false);
		ttsEnabled.set(false);
		ttsConfigured.set(false);
		voiceModeSttMode.set('browser');
	}
}
