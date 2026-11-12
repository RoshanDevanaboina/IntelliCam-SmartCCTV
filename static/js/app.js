/**
 * CC TV — Frontend Application
 * Handles WebSocket connections, notifications, and UI interactions.
 */

// ─── WebSocket Connection ───────────────────────────────────────────────────

const socket = io({ transports: ['websocket', 'polling'] });

socket.on('connect', () => {
    console.log('WebSocket connected');
    updateConnectionBadge(true);
});

socket.on('disconnect', () => {
    console.log('WebSocket disconnected');
    updateConnectionBadge(false);
});

socket.on('connect_error', () => {
    updateConnectionBadge(false);
});

// ─── Connection Badge ───────────────────────────────────────────────────────

function updateConnectionBadge(connected) {
    const badge = document.getElementById('connection-badge');
    const text = document.getElementById('connection-text');
    if (!badge || !text) return;

    if (connected) {
        badge.className = 'badge badge-online';
        text.textContent = 'Live';
    } else {
        badge.className = 'badge badge-offline';
        text.textContent = 'Offline';
    }
}

// ─── Detection Event Notifications ──────────────────────────────────────────

let unreadNotifications = 0;

socket.on('detection_event', (data) => {
    console.log('Detection event:', data);

    // Update notification counter
    unreadNotifications++;
    const countBadge = document.getElementById('notification-count');
    if (countBadge) {
        countBadge.textContent = unreadNotifications;
        countBadge.classList.remove('hidden');
    }

    // Show toast notification
    const typeEmoji = {
        motion: '🏃',
        person: '🧑',
        car: '🚗',
        truck: '🚛',
        dog: '🐕',
        cat: '🐈',
        bird: '🐦',
        bicycle: '🚲',
        motorcycle: '🏍️',
        bus: '🚌',
    }[data.type] || '⚠️';

    const confidence = data.confidence ? ` (${(data.confidence * 100).toFixed(0)}%)` : '';
    showToast(
        `${typeEmoji} ${data.type.charAt(0).toUpperCase() + data.type.slice(1)}${confidence} — ${data.camera_name}`,
        data.type === 'motion' ? 'info' : 'warning'
    );
});

// Reset notification count when bell is clicked
document.addEventListener('DOMContentLoaded', () => {
    const bell = document.getElementById('notification-bell');
    if (bell) {
        bell.addEventListener('click', () => {
            unreadNotifications = 0;
            const countBadge = document.getElementById('notification-count');
            if (countBadge) {
                countBadge.classList.add('hidden');
            }
            // Navigate to events page
            window.location.href = '/events';
        });
    }
});

// ─── Toast Notifications ────────────────────────────────────────────────────

function showToast(message, type = 'info', duration = 4000) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const icons = {
        success: 'fas fa-check-circle',
        error: 'fas fa-exclamation-circle',
        warning: 'fas fa-exclamation-triangle',
        info: 'fas fa-info-circle',
    };

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <i class="${icons[type] || icons.info}"></i>
        <span>${message}</span>
    `;

    container.appendChild(toast);

    // Auto-dismiss
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease forwards';
        setTimeout(() => toast.remove(), 300);
    }, duration);

    // Click to dismiss
    toast.addEventListener('click', () => {
        toast.style.animation = 'slideOut 0.3s ease forwards';
        setTimeout(() => toast.remove(), 300);
    });
}

// ─── Dropdown Menu ──────────────────────────────────────────────────────────

function toggleDropdown(button) {
    const menu = button.nextElementSibling;
    const isOpen = !menu.classList.contains('hidden');

    // Close all other dropdowns
    document.querySelectorAll('.dropdown-menu').forEach(m => m.classList.add('hidden'));

    if (!isOpen) {
        menu.classList.remove('hidden');
    }
}

// Close dropdowns when clicking outside
document.addEventListener('click', (e) => {
    if (!e.target.closest('.dropdown')) {
        document.querySelectorAll('.dropdown-menu').forEach(m => m.classList.add('hidden'));
    }
});

// ─── Keyboard Shortcuts ─────────────────────────────────────────────────────

document.addEventListener('keydown', (e) => {
    // Escape closes modals
    if (e.key === 'Escape') {
        const modal = document.getElementById('event-modal');
        if (modal && !modal.classList.contains('hidden')) {
            modal.classList.add('hidden');
        }
        // Exit fullscreen
        if (document.fullscreenElement) {
            document.exitFullscreen();
        }
    }

    // 1-3 keys switch grid view on dashboard
    if (!e.target.matches('input, textarea, select')) {
        if (e.key === '1') setGridSize?.(1);
        if (e.key === '2') setGridSize?.(2);
        if (e.key === '3') setGridSize?.(3);
    }
});

// ─── Utility Functions ──────────────────────────────────────────────────────

function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function timeAgo(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const seconds = Math.floor((now - date) / 1000);

    if (seconds < 60) return 'just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
}
