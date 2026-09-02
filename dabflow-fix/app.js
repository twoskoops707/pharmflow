/**
 * DabFlow - Core Application
 * Built by Claude AI for twoskoops707
 */

console.log('🔥 DabFlow Starting...');

// === AGE VERIFICATION ===
function initializeAgeGate() {
    console.log('🔒 Initializing age gate...');

    const ageGate = document.getElementById('age-gate');
    const app = document.getElementById('app');
    const yesBtn = document.getElementById('age-yes-btn');
    const noBtn = document.getElementById('age-no-btn');

    console.log('Age gate elements:', {
        ageGate: !!ageGate,
        app: !!app,
        yesBtn: !!yesBtn,
        noBtn: !!noBtn
    });

    // Check if already verified
    const isVerified = localStorage.getItem('dabflow_age_verified');
    console.log('Age verified:', isVerified);

    if (isVerified === 'true') {
        // Already verified, show app
        console.log('✅ Already verified, showing app');
        if (ageGate) ageGate.style.display = 'none';
        if (app) app.style.display = 'flex';
        if (typeof mantis !== 'undefined') mantis.push(['display', 'refresh']);
        return true;
    }

    // Handle YES button
    if (yesBtn) {
        const handleYesClick = () => {
            console.log('🎉 YES clicked!');
            localStorage.setItem('dabflow_age_verified', 'true');
            ageGate.style.opacity = '0';
            ageGate.style.transition = 'opacity 0.5s ease';
            setTimeout(() => {
                ageGate.style.display = 'none';
                app.style.display = 'flex';
                console.log('🚀 App shown, initializing...');
                if (typeof mantis !== 'undefined') mantis.push(['display', 'refresh']);
                initializeApp();
            }, 500);
            try {
                haptic('medium');
            } catch (e) {
                console.log('Haptic not available');
            }
        };

        // Add listener via addEventListener
        yesBtn.addEventListener('click', handleYesClick);

        // BACKUP: Also set onclick directly
        yesBtn.onclick = handleYesClick;

    } else {
        console.error('❌ YES button not found!');
    }

    // Handle NO button
    if (noBtn) {
        console.log('✅ NO button found, adding listener');
        noBtn.addEventListener('click', () => {
            console.log('❌ NO clicked');
            alert('You must be 21 years or older to use this app.');
            try {
                haptic('heavy');
            } catch (e) {
                console.log('Haptic not available');
            }
        });
    } else {
        console.error('❌ NO button not found!');
    }

    console.log('🔒 Age gate initialization complete');
    return false;
}

// === STATE MANAGEMENT ===
const state = {
    settings: {
        material: 'quartz',
        concentrate: 'shatter',
        heater: 'butane',
        theme: 'neon-cyber',
        isPremium: false,
        useCustomTimes: false,
        customHeatTime: 18,
        customCoolTime: 60
    },
    timer: {
        isRunning: false,
        isPaused: false,
        mode: 'heat', // 'heat' or 'cool'
        timeLeft: 0,
        totalTime: 0,
        heatTime: 0,
        coolTime: 0,
        interval: null
    },
    stats: {
        totalSessions: 0,
        streak: 0,
        lastSessionDate: null,
        sessions: [],
        achievements: []
    },
    charts: {
        activity: null,
        materialPie: null,
        concentratePie: null,
        heaterPie: null,
        timePie: null
    }
};

// === TIMER CONFIGS (Based on real-world temperature science) ===
const CONFIG = {
    // SAFETY LIMITS
    maxHeatTime: 20,  // Maximum heat time in seconds (safety limit)
    minCoolTime: 50,  // Minimum cool time in seconds (safety limit)
    maxCoolTime: 85,  // Maximum cool time in seconds

    // OPTIMAL DAB TEMPERATURES (in Fahrenheit)
    // Based on proper low-temp dabbing for best flavor and smoothness
    optimalTemp: {
        quartz: 500,      // 450-550°F ideal range - best flavor
        titanium: 520,    // 500-550°F ideal range - retains heat well
        ceramic: 480      // 450-500°F ideal range - smooth and flavorful
    },

    materials: {
        // Quartz: Medium heat retention, standard cool down
        quartz: { heatUp: 18, coolDown: 60 },
        // Titanium: Fast heat, retains heat longer
        titanium: { heatUp: 15, coolDown: 70 },
        // Ceramic: Slow heat, longest cool down for even temp
        ceramic: { heatUp: 20, coolDown: 75 }
    },
    heaters: {
        // Butane: Standard torch, slightly slower
        butane: { heatModifier: 1.1, coolModifier: 1.0 },
        // Propane: Hotter flame, max 20s to red hot, faster cool
        propane: { heatModifier: 1.0, coolModifier: 0.95 }
    },
    concentrates: {
        shatter: { coolModifier: 1.0 },
        wax: { coolModifier: 0.93 },
        'live-resin': { coolModifier: 1.05 },
        rosin: { coolModifier: 1.08 },
        diamonds: { coolModifier: 1.15 },
        crumble: { coolModifier: 0.95 },
        budder: { coolModifier: 0.97 },
        sauce: { coolModifier: 1.10 },
        'hash-rosin': { coolModifier: 1.12 },
        distillate: { coolModifier: 0.90 }
    }
};

// === ACHIEVEMENTS (with theme unlocks) ===
const ACHIEVEMENTS = [
    // Starter Achievements (Session Milestones)
    { id: 'first-flame', name: 'First Flame', icon: '🔥', description: 'Complete your first session', type: 'sessions', requirement: 1, unlocked: false, unlocksTheme: null, unlocksFeature: 'Tutorial Badge' },
    { id: 'hot-starter', name: 'Hot Starter', icon: '⚡', description: 'Complete 5 sessions', type: 'sessions', requirement: 5, unlocked: false, unlocksTheme: 'lava-flow', unlocksFeature: 'Lava Flow Theme' },
    { id: 'dedicated', name: 'Dedicated', icon: '💪', description: 'Complete 25 sessions', type: 'sessions', requirement: 25, unlocked: false, unlocksTheme: 'ice-crystal', unlocksFeature: 'Ice Crystal Theme' },
    { id: 'veteran', name: 'Veteran', icon: '🎖️', description: 'Complete 50 sessions', type: 'sessions', requirement: 50, unlocked: false, unlocksTheme: 'golden-amber', unlocksFeature: 'Golden Amber Theme' },
    { id: 'century-club', name: 'Century Club', icon: '💯', description: 'Complete 100 sessions', type: 'sessions', requirement: 100, unlocked: false, unlocksTheme: 'aurora-borealis', unlocksFeature: 'Aurora Borealis Theme' },
    { id: 'marathon-runner', name: 'Marathon Runner', icon: '🏃', description: 'Complete 250 sessions - Elite status!', type: 'sessions', requirement: 250, unlocked: false, unlocksTheme: null, unlocksFeature: 'Custom Notification Sounds' },

    // Elite Tier (High Session Counts)
    { id: 'stoner-for-life', name: 'Stoner for Life', icon: '🌿', description: '500 sessions completed - Ultimate legend status', type: 'sessions', requirement: 500, unlocked: false, unlocksTheme: 'stoner-paradise', unlocksFeature: 'Stoner Paradise Theme + Special Badge' },
    { id: 'up-in-smoke', name: 'Up in Smoke', icon: '🚬', description: '1000 sessions - You reached legendary Cheech & Chong status!', type: 'sessions', requirement: 1000, unlocked: false, unlocksTheme: 'cheech-and-chong', unlocksFeature: 'Cheech & Chong Theme + Hall of Fame' },

    // Streak Achievements (Consistency)
    { id: 'weekend-warrior', name: 'Weekend Warrior', icon: '🗓️', description: '3 day streak', type: 'streak', requirement: 3, unlocked: false, unlocksTheme: null, unlocksFeature: 'Bronze Streak Badge' },
    { id: 'week-warrior', name: 'Week Warrior', icon: '📅', description: '7 day streak', type: 'streak', requirement: 7, unlocked: false, unlocksTheme: 'ocean-teal', unlocksFeature: 'Ocean Teal Theme + Silver Badge' },
    { id: 'month-master', name: 'Month Master', icon: '📆', description: '30 day streak', type: 'streak', requirement: 30, unlocked: false, unlocksTheme: 'crimson-red', unlocksFeature: 'Crimson Red Theme + Gold Badge' },
    { id: 'unbreakable', name: 'Unbreakable', icon: '⚡', description: '90 day streak - Legendary consistency!', type: 'streak', requirement: 90, unlocked: false, unlocksTheme: null, unlocksFeature: 'Platinum Streak Badge' },

    // Material Specialist Achievements
    { id: 'quartz-king', name: 'Quartz King', icon: '👑', description: 'Use quartz 25 times', type: 'material', material: 'quartz', requirement: 25, unlocked: false, unlocksTheme: 'ice-crystal', unlocksFeature: 'Quartz Master Badge' },
    { id: 'titanium-titan', name: 'Titanium Titan', icon: '🛡️', description: 'Use titanium 25 times', type: 'material', material: 'titanium', requirement: 25, unlocked: false, unlocksTheme: null, unlocksFeature: 'Titanium Expert Badge' },
    { id: 'ceramic-connoisseur', name: 'Ceramic Connoisseur', icon: '🏺', description: 'Use ceramic 25 times', type: 'material', material: 'ceramic', requirement: 25, unlocked: false, unlocksTheme: null, unlocksFeature: 'Ceramic Specialist Badge' },

    // Concentrate Master Achievements
    { id: 'shatter-master', name: 'Shatter Master', icon: '💎', description: 'Use shatter 20 times', type: 'concentrate', concentrate: 'shatter', requirement: 20, unlocked: false, unlocksTheme: null, unlocksFeature: 'Crystal Effects Filter' },
    { id: 'rosin-royalty', name: 'Rosin Royalty', icon: '🍯', description: 'Use rosin 20 times', type: 'concentrate', concentrate: 'rosin', requirement: 20, unlocked: false, unlocksTheme: null, unlocksFeature: 'Gold Particle Effects' },
    { id: 'diamond-dealer', name: 'Diamond Dealer', icon: '💠', description: 'Use diamonds 20 times', type: 'concentrate', concentrate: 'diamonds', requirement: 20, unlocked: false, unlocksTheme: null, unlocksFeature: 'Diamond Sparkle Effects' },
    { id: 'sauce-boss', name: 'Sauce Boss', icon: '🌊', description: 'Use sauce 20 times', type: 'concentrate', concentrate: 'sauce', requirement: 20, unlocked: false, unlocksTheme: null, unlocksFeature: 'Wave Animation Effects' },
    { id: 'live-resin-legend', name: 'Live Resin Legend', icon: '💧', description: 'Use live resin 20 times', type: 'concentrate', concentrate: 'live-resin', requirement: 20, unlocked: false, unlocksTheme: null, unlocksFeature: 'Resin Flow Effects' },
    { id: 'hash-hero', name: 'Hash Hero', icon: '🥇', description: 'Use hash rosin 20 times', type: 'concentrate', concentrate: 'hash-rosin', requirement: 20, unlocked: false, unlocksTheme: null, unlocksFeature: 'Premium Hash Badge' },

    // Special Time-Based Achievements
    { id: 'night-owl', name: 'Night Owl', icon: '🦉', description: 'Complete 10 sessions between midnight-4am', type: 'time', requirement: 10, timeRange: [0, 4], unlocked: false, unlocksTheme: null, unlocksFeature: 'Midnight Mode Theme' },
    { id: 'early-bird', name: 'Early Bird', icon: '🌅', description: 'Complete 10 sessions between 6am-9am', type: 'time', requirement: 10, timeRange: [6, 9], unlocked: false, unlocksTheme: null, unlocksFeature: 'Sunrise Theme' },

    // Mastery Achievements
    { id: 'perfect-precision', name: 'Perfect Precision', icon: '🎯', description: 'Complete 10 sessions with custom times', type: 'custom', requirement: 10, unlocked: false, unlocksTheme: null, unlocksFeature: 'Advanced Timer Presets' },
    { id: 'variety-king', name: 'Variety King', icon: '🌈', description: 'Use all 10 concentrate types at least once', type: 'variety', requirement: 10, unlocked: false, unlocksTheme: null, unlocksFeature: 'Rainbow Theme' },
    { id: 'equipment-expert', name: 'Equipment Expert', icon: '⚙️', description: 'Use all material types 10 times each', type: 'equipment', requirement: 30, unlocked: false, unlocksTheme: null, unlocksFeature: 'Equipment Comparison Chart' },

    // Ultimate Master Achievement
    { id: 'the-dabologist', name: 'The Dabologist', icon: '🔬', description: 'Unlock all other achievements - True Master!', type: 'meta', requirement: 24, unlocked: false, unlocksTheme: null, unlocksFeature: 'Galaxy Theme + Master Dabber Title + Custom App Icon' }
];

// === INITIALIZATION ===
function initializeApp() {
    console.log('✓ DOM Ready');
    loadState();
    handleURLActions(); // Handle shortcuts from home screen
    initializeNavigation();
    initializeTimer();
    initializeSettings();
    initTempUnitSelector();
    initializeStats();
    initializeHapticFeedback();
    updateUI();
}

// Handle URL-based actions (from home screen shortcuts)
function handleURLActions() {
    const urlParams = new URLSearchParams(window.location.search);
    const action = urlParams.get('action');
    const premium = urlParams.get('premium');

    // Handle Stripe payment success
    if (premium === 'success') {
        setTimeout(() => {
            activatePremium();
            showToast('👑 Welcome to Premium! Ads removed & all features unlocked!', 'success');
            // Clean up URL
            window.history.replaceState({}, document.title, window.location.pathname);
        }, 500);
    } else if (action === 'quick-start') {
        // Wait a moment for UI to load, then auto-start timer
        setTimeout(() => {
            console.log('🚀 Quick-start shortcut activated!');
            startTimer();
            showToast('🔥 Quick Start activated!', 'success');
        }, 500);
    } else if (action === 'stats') {
        // Navigate to stats screen
        setTimeout(() => {
            switchScreen('stats');
        }, 300);
    }
}

// === LOAD STATE FROM LOCALSTORAGE ===
function loadState() {
    const saved = localStorage.getItem('dabflow_state');
    if (saved) {
        const parsed = JSON.parse(saved);
        state.settings = { ...state.settings, ...parsed.settings };
        state.stats = { ...state.stats, ...parsed.stats };
    }

    // 🧪 DEBUG BUILD FLAG - Set to true to unlock everything for testing
    const DEBUG_MODE = false;

    // Initialize stats arrays if they don't exist
    if (!state.stats.sessions) state.stats.sessions = [];
    if (!state.stats.achievements) state.stats.achievements = [];
    if (!state.stats.unlockedThemes) state.stats.unlockedThemes = [];

    if (DEBUG_MODE) {
        // 🧪 DEBUG BUILD: Auto-unlock premium and all features for testing
        state.settings.isPremium = true;

        // Unlock all achievements
        ACHIEVEMENTS.forEach(ach => {
            ach.unlocked = true;
            if (!state.stats.achievements.includes(ach.id)) {
                state.stats.achievements.push(ach.id);
            }
        });

        // Set realistic test stats
        if (state.stats.totalSessions === 0) {
            state.stats.totalSessions = 42;
            state.stats.streak = 7;
            state.stats.bestStreak = 15;
            state.stats.mostInDay = 5;
        }

        // Unlock all themes
        const allThemes = [
            'neon-cyber', 'emerald-green', 'sapphire-blue', 'amethyst-purple',
            'sunset-orange', 'bubblegum-pink', 'lava-flow', 'ice-crystal',
            'golden-amber', 'aurora-borealis', 'ocean-teal', 'crimson-red',
            'stoner-paradise', 'cheech-and-chong'
        ];
        state.stats.unlockedThemes = allThemes;

        console.log('🧪 DEBUG MODE: Premium + All Achievements + All Themes UNLOCKED');
        console.log(`📊 Debug Stats: ${state.stats.totalSessions} sessions, ${state.stats.streak} day streak`);
        console.log(`🏆 Achievements: ${state.stats.achievements.length}/${ACHIEVEMENTS.length} unlocked`);
        console.log(`🎨 Themes: ${state.stats.unlockedThemes.length}/14 unlocked`);
    } else {
        // Initialize base themes (6 unlocked by default)
        const defaultThemes = [
            'neon-cyber', 'emerald-green', 'sapphire-blue',
            'amethyst-purple', 'sunset-orange', 'bubblegum-pink'
        ];

        // Add default themes if first time user
        if (state.stats.unlockedThemes.length === 0) {
            state.stats.unlockedThemes = [...defaultThemes];
        }

        // Check and unlock achievement-based themes
        state.stats.achievements.forEach(achId => {
            const achievement = ACHIEVEMENTS.find(a => a.id === achId);
            if (achievement && achievement.unlocksTheme) {
                if (!state.stats.unlockedThemes.includes(achievement.unlocksTheme)) {
                    state.stats.unlockedThemes.push(achievement.unlocksTheme);
                }
            }
        });

        // Premium users get all themes instantly
        if (state.settings.isPremium) {
            const allThemes = [
                'neon-cyber', 'emerald-green', 'sapphire-blue', 'amethyst-purple',
                'sunset-orange', 'bubblegum-pink', 'lava-flow', 'ice-crystal',
                'golden-amber', 'aurora-borealis', 'ocean-teal', 'crimson-red',
                'stoner-paradise', 'cheech-and-chong'
            ];
            state.stats.unlockedThemes = allThemes;
        }

        console.log('✓ Production Build: Themes locked by achievement progress');
        console.log(`📊 Stats: ${state.stats.totalSessions} sessions, ${state.stats.streak} day streak`);
        console.log(`🏆 Achievements: ${state.stats.achievements.length}/${ACHIEVEMENTS.length} unlocked`);
        console.log(`🎨 Themes: ${state.stats.unlockedThemes.length}/14 unlocked`);
    }

    // Apply saved theme
    document.body.setAttribute('data-theme', state.settings.theme);

    console.log('✓ State Loaded', state);
}

// === SAVE STATE TO LOCALSTORAGE ===
function saveState() {
    localStorage.setItem('dabflow_state', JSON.stringify({
        settings: state.settings,
        stats: state.stats
    }));
}

// === NAVIGATION ===
function initializeNavigation() {
    const navItems = document.querySelectorAll('.nav-item');
    const screens = document.querySelectorAll('.screen');

    console.log('📱 Found nav items:', navItems.length);
    console.log('📱 Found screens:', screens.length);

    if (navItems.length === 0) {
        console.error('❌ No navigation items found!');
        return;
    }

    navItems.forEach((item, index) => {
        console.log(`Setting up nav item ${index}:`, item.dataset.screen);

        item.addEventListener('click', (e) => {
            e.preventDefault();
            const screenName = item.dataset.screen;
            switchScreen(screenName);
            haptic('light');
        });
    });

    console.log('✓ Navigation Initialized');
}

// === TOAST NOTIFICATIONS ===
function showToast(message, type = 'info') {
    // Remove any existing toast
    const existingToast = document.querySelector('.toast-notification');
    if (existingToast) {
        existingToast.remove();
    }

    // Create toast element
    const toast = document.createElement('div');
    toast.className = `toast-notification toast-${type}`;
    toast.textContent = message;
    toast.style.cssText = `
        position: fixed;
        bottom: 80px;
        left: 50%;
        transform: translateX(-50%);
        background: rgba(0, 0, 0, 0.9);
        color: white;
        padding: 12px 24px;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 600;
        z-index: 10000;
        animation: slideUp 0.3s ease;
        max-width: 90%;
        text-align: center;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    `;

    // Type-specific styling
    if (type === 'success') {
        toast.style.background = 'rgba(0, 200, 83, 0.95)';
    } else if (type === 'warning') {
        toast.style.background = 'rgba(255, 152, 0, 0.95)';
    } else if (type === 'error') {
        toast.style.background = 'rgba(244, 67, 54, 0.95)';
    }

    document.body.appendChild(toast);

    // Auto-remove after 3 seconds
    setTimeout(() => {
        toast.style.animation = 'slideDown 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// Helper function to switch screens
function switchScreen(screenName) {
    console.log(`🔄 Switching to screen: ${screenName}`);

    const navItems = document.querySelectorAll('.nav-item');
    const screens = document.querySelectorAll('.screen');

    // Update nav active state
    navItems.forEach(nav => nav.classList.remove('active'));
    const targetNav = document.querySelector(`[data-screen="${screenName}"]`);
    if (targetNav) {
        targetNav.classList.add('active');
    }

    // Update screen visibility
    screens.forEach(screen => {
        screen.classList.remove('active');
        console.log(`Hiding screen: ${screen.id}`);
    });

    const targetScreen = document.getElementById(`${screenName}-screen`);
    if (targetScreen) {
        targetScreen.classList.add('active');
        console.log(`✅ Showing screen: ${screenName}-screen`);

        // Scroll to top of the screen
        targetScreen.scrollTop = 0;

        // Also scroll main container to top if exists
        const appContainer = document.getElementById('app');
        if (appContainer) {
            appContainer.scrollTop = 0;
        }

        // Scroll window to top as well
        window.scrollTo(0, 0);
    } else {
        console.error(`❌ Screen not found: ${screenName}-screen`);
    }

    // Update stats if viewing stats screen
    if (screenName === 'stats') {
        updateStatsDisplay();
    }

    // Scroll to top when switching screens
    const main = document.querySelector('main');
    if (main) {
        main.scrollTop = 0;
    }

    // Show/hide timer ad banner based on premium status
    if (screenName === 'timer') {
        const timerAdBanner = document.getElementById('timer-ad-banner');
        if (timerAdBanner) {
            timerAdBanner.style.display = state.settings.isPremium ? 'none' : 'block';
        }
    }
}

// === SETTINGS UI ===
function initializeSettings() {
    // Set active states for current settings
    const optionButtons = document.querySelectorAll('.option-btn');
    optionButtons.forEach(btn => {
        const setting = btn.dataset.setting;
        const value = btn.dataset.value;

        // Set active if matches current state
        if (state.settings[setting] === value) {
            btn.classList.add('active');
        }

        btn.addEventListener('click', () => {
            // Update active state within group
            document.querySelectorAll(`[data-setting="${setting}"]`).forEach(b => {
                b.classList.remove('active');
            });
            btn.classList.add('active');

            // Update state
            state.settings[setting] = value;
            saveState();
            haptic('light');

            console.log(`✓ ${setting} set to ${value}`);
        });
    });

    // Theme selector
    const themeOptions = document.querySelectorAll('.theme-option');
    themeOptions.forEach(option => {
        const theme = option.dataset.theme;
        const achievement = option.dataset.achievement;

        // Check if theme is unlocked
        const isThemeUnlocked = state.stats.unlockedThemes && state.stats.unlockedThemes.includes(theme);

        // Update visual state based on unlock status
        if (isThemeUnlocked) {
            option.classList.remove('locked');
            option.classList.add('unlocked');
        } else {
            option.classList.add('locked');
            option.classList.remove('unlocked');
        }

        // Set active if matches current theme
        if (state.settings.theme === theme) {
            option.classList.add('active');
        }

        option.addEventListener('click', () => {
            // Re-check lock status
            const stillLocked = !state.stats.unlockedThemes.includes(theme);

            if (stillLocked && !state.settings.isPremium) {
                const achData = ACHIEVEMENTS.find(a => a.id === achievement);
                if (achData) {
                    showToast(`🔒 Locked! ${achData.description}`, 'warning');
                } else {
                    showToast('🔒 This theme is locked!', 'warning');
                }
                haptic('medium');
                return;
            }

            // Apply theme
            document.body.setAttribute('data-theme', theme);
            state.settings.theme = theme;
            saveState();

            // Update active state
            themeOptions.forEach(opt => opt.classList.remove('active'));
            option.classList.add('active');

            showToast('🎨 Theme changed!', 'success');
            haptic('light');
        });
    });

    // Premium upgrade button
    const upgradeBtn = document.getElementById('upgrade-btn');
    const restorePurchaseBtn = document.getElementById('restore-purchase-btn');
    const restorePurchaseBtn2 = document.getElementById('restore-purchase-btn-2');

    if (upgradeBtn) {
        upgradeBtn.addEventListener('click', handlePremiumPurchase);
    }

    if (restorePurchaseBtn) {
        restorePurchaseBtn.addEventListener('click', restorePremiumPurchase);
    }

    if (restorePurchaseBtn2) {
        restorePurchaseBtn2.addEventListener('click', restorePremiumPurchase);
    }

    // Initialize premium state
    updatePremiumUI();

    // Custom times toggle
    const customTimesToggle = document.getElementById('custom-times-toggle');
    const customTimesInputs = document.getElementById('custom-times-inputs');
    const customHeatInput = document.getElementById('custom-heat-time');
    const customCoolInput = document.getElementById('custom-cool-time');

    if (customTimesToggle) {
        // Set initial state
        customTimesToggle.checked = state.settings.useCustomTimes;
        if (state.settings.useCustomTimes) {
            customTimesInputs.style.display = 'block';
        }

        customTimesToggle.addEventListener('change', () => {
            state.settings.useCustomTimes = customTimesToggle.checked;
            customTimesInputs.style.display = customTimesToggle.checked ? 'block' : 'none';
            saveState();
            haptic('light');
            console.log(`✓ Custom times ${customTimesToggle.checked ? 'enabled' : 'disabled'}`);
        });
    }

    if (customHeatInput) {
        customHeatInput.value = state.settings.customHeatTime;
        customHeatInput.addEventListener('change', () => {
            let heatTime = parseInt(customHeatInput.value) || 18;
            // Enforce safety limit: max 20s
            if (heatTime > CONFIG.maxHeatTime) {
                heatTime = CONFIG.maxHeatTime;
                customHeatInput.value = heatTime;
                // showToast(`⚠️ Heat time capped at ${CONFIG.maxHeatTime}s for safety`, 'warning');
            }
            state.settings.customHeatTime = heatTime;
            saveState();
        });
    }

    if (customCoolInput) {
        customCoolInput.value = state.settings.customCoolTime;
        customCoolInput.addEventListener('change', () => {
            let coolTime = parseInt(customCoolInput.value) || 60;
            // Enforce safety limit: min 50s
            if (coolTime < CONFIG.minCoolTime) {
                coolTime = CONFIG.minCoolTime;
                customCoolInput.value = coolTime;
                // showToast(`⚠️ Cool time must be at least ${CONFIG.minCoolTime}s for safety`, 'warning');
            }
            if (coolTime > CONFIG.maxCoolTime) {
                coolTime = CONFIG.maxCoolTime;
                customCoolInput.value = coolTime;
            }
            state.settings.customCoolTime = coolTime;
            saveState();
        });
    }

    console.log('✓ Settings Initialized');
}

// === TIMER LOGIC ===
function initializeTimer() {
    const startBtn = document.getElementById('start-dab-btn');
    const pauseBtn = document.getElementById('pause-btn');
    const resetBtn = document.getElementById('reset-btn');

    console.log('⏱️  Timer elements:', { startBtn: !!startBtn, pauseBtn: !!pauseBtn, resetBtn: !!resetBtn });

    if (!startBtn) {
        console.error('❌ Start button not found!');
        return;
    }

    startBtn.addEventListener('click', (e) => {
        console.log('🚀 Start button clicked!');
        e.preventDefault();
        startTimer();
    });

    if (pauseBtn) {
        pauseBtn.addEventListener('click', (e) => {
            e.preventDefault();
            pauseTimer();
        });
    }

    if (resetBtn) {
        resetBtn.addEventListener('click', (e) => {
            e.preventDefault();
            resetTimer();
        });
    }

    console.log('✓ Timer Initialized');
}

function calculateTimings() {
    // Use custom times if enabled, otherwise calculate
    if (state.settings.useCustomTimes) {
        state.timer.heatTime = state.settings.customHeatTime;
        state.timer.coolTime = state.settings.customCoolTime;
    } else {
        const material = CONFIG.materials[state.settings.material];
        const heater = CONFIG.heaters[state.settings.heater];
        const concentrate = CONFIG.concentrates[state.settings.concentrate];

        state.timer.heatTime = Math.round(material.heatUp * heater.heatModifier);
        state.timer.coolTime = Math.round(material.coolDown * heater.coolModifier * concentrate.coolModifier);
    }

    // APPLY SAFETY LIMITS (CRITICAL FOR USER SAFETY)
    if (state.timer.heatTime > CONFIG.maxHeatTime) {
        console.warn(`⚠️ Heat time ${state.timer.heatTime}s exceeds safe limit, capping at ${CONFIG.maxHeatTime}s`);
        state.timer.heatTime = CONFIG.maxHeatTime;
    }

    if (state.timer.coolTime < CONFIG.minCoolTime) {
        console.warn(`⚠️ Cool time ${state.timer.coolTime}s below safe limit, setting to ${CONFIG.minCoolTime}s`);
        state.timer.coolTime = CONFIG.minCoolTime;
    }

    if (state.timer.coolTime > CONFIG.maxCoolTime) {
        console.log(`ℹ️ Cool time ${state.timer.coolTime}s exceeds ${CONFIG.maxCoolTime}s, capping`);
        state.timer.coolTime = CONFIG.maxCoolTime;
    }

    state.timer.totalTime = state.timer.heatTime + state.timer.coolTime;
    state.timer.optimalTemp = CONFIG.optimalTemp[state.settings.material];

    console.log(`✓ Final times: Heat ${state.timer.heatTime}s, Cool ${state.timer.coolTime}s, Target ${state.timer.optimalTemp}°F`);
}

function startTimer() {
    console.log('🔥 Starting timer with settings:', state.settings);

    // FORCE SCROLL TO TOP IMMEDIATELY - before anything else
    window.scrollTo(0, 0);
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;

    // Calculate timings
    calculateTimings();

    // Set initial state
    state.timer.mode = 'heat';
    state.timer.timeLeft = state.timer.heatTime;
    state.timer.isRunning = true;
    state.timer.isPaused = false;

    console.log('⏱️  Timer state:', state.timer);

    // Switch to timer screen manually
    const timerNavItem = document.querySelector('[data-screen="timer"]');
    if (timerNavItem) {
        console.log('📱 Found timer nav item, switching screens...');

        // Hide all screens
        document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));

        // Show timer screen
        const timerScreen = document.getElementById('timer-screen');
        if (timerScreen) {
            timerScreen.classList.add('active');
            console.log('✅ Timer screen is now visible');

            // Scroll to top of timer screen - MULTIPLE attempts with increasing delays
            // Force immediate scroll
            timerScreen.scrollTop = 0;
            window.scrollTo(0, 0);
            document.documentElement.scrollTop = 0;

            // Then scroll again after short delay
            setTimeout(() => {
                timerScreen.scrollTop = 0;
                const appContainer = document.getElementById('app');
                if (appContainer) {
                    appContainer.scrollTop = 0;
                }
                window.scrollTo(0, 0);
                document.body.scrollTop = 0;
                document.documentElement.scrollTop = 0;
            }, 50);

            // After screen transition animation (300ms)
            setTimeout(() => {
                timerScreen.scrollTop = 0;
                window.scrollTo(0, 0);
                document.documentElement.scrollTop = 0;
                const appContainer = document.getElementById('app');
                if (appContainer) {
                    appContainer.scrollTop = 0;
                }
            }, 350);

            // Final scroll after everything settles
            setTimeout(() => {
                timerScreen.scrollTop = 0;
                window.scrollTo(0, 0);
                document.documentElement.scrollTop = 0;
                document.body.scrollTop = 0;
            }, 500);
        }

        // Update nav active state
        document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
        timerNavItem.classList.add('active');
    } else {
        console.error('❌ Timer nav item not found!');
    }

    // Update session info
    const materialEl = document.getElementById('session-material');
    const concentrateEl = document.getElementById('session-concentrate');
    const heaterEl = document.getElementById('session-heater');
    const heatTimeEl = document.getElementById('session-heat-time');
    const coolTimeEl = document.getElementById('session-cool-time');
    const totalTimeEl = document.getElementById('session-total-time');
    const optimalTempEl = document.getElementById('session-optimal-temp');

    if (materialEl) materialEl.textContent = state.settings.material.charAt(0).toUpperCase() + state.settings.material.slice(1);
    if (concentrateEl) {
        // Format concentrate name (e.g., "live-resin" -> "Live Resin")
        const formatted = state.settings.concentrate.split('-').map(word =>
            word.charAt(0).toUpperCase() + word.slice(1)
        ).join(' ');
        concentrateEl.textContent = formatted;
    }
    if (heaterEl) heaterEl.textContent = state.settings.heater.charAt(0).toUpperCase() + state.settings.heater.slice(1);
    if (heatTimeEl) heatTimeEl.textContent = state.timer.heatTime;
    if (coolTimeEl) coolTimeEl.textContent = state.timer.coolTime;
    if (totalTimeEl) totalTimeEl.textContent = state.timer.totalTime;
    if (optimalTempEl) optimalTempEl.textContent = displayTemperature(state.timer.optimalTemp || 550);

    const videoAdStart = document.getElementById('cooldown-video-ad');
    if (videoAdStart) videoAdStart.style.display = 'none';

    // Start countdown
    runTimer();

    // FORCE SCROLL TO TOP AFTER EVERYTHING IS RENDERED
    // Multiple attempts with increasing delays to ensure it works
    const forceScrollToTop = () => {
        window.scrollTo({ top: 0, behavior: 'instant' });
        document.documentElement.scrollTop = 0;
        document.body.scrollTop = 0;
        const timerScreen = document.getElementById('timer-screen');
        if (timerScreen) timerScreen.scrollTop = 0;
        const appContainer = document.getElementById('app');
        if (appContainer) appContainer.scrollTop = 0;
        const main = document.querySelector('main');
        if (main) main.scrollTop = 0;
    };

    setTimeout(forceScrollToTop, 100);
    setTimeout(forceScrollToTop, 300);
    setTimeout(forceScrollToTop, 600);
    setTimeout(forceScrollToTop, 1000);

    console.log('✓ Timer Started');
}

function runTimer() {
    if (state.timer.interval) clearInterval(state.timer.interval);

    state.timer.interval = setInterval(() => {
        if (!state.timer.isRunning || state.timer.isPaused) return;

        state.timer.timeLeft--;

        // Update display
        updateTimerDisplay();

        // Check if phase complete
        if (state.timer.timeLeft <= 0) {
            if (state.timer.mode === 'heat') {
                // Switch to cool phase
                state.timer.mode = 'cool';
                state.timer.timeLeft = state.timer.coolTime;
                // showToast('🔥 Flame OFF! Start cooling...', 'success'); // Removed - looks cheap
                playSound('heatComplete');
                if (!state.settings.isPremium) {
                    const videoAd = document.getElementById('cooldown-video-ad');
                    if (videoAd) {
                        videoAd.style.display = 'block';
                        if (!videoAd.querySelector('[data-mantis-zone]')) {
                            videoAd.innerHTML = '<div data-mantis-zone="zone-two"></div>';
                        }
                        if (typeof mantis !== 'undefined') {
                            setTimeout(function() {
                                mantis.push(['display', 'refresh', 'zone-two']);
                            }, 300);
                        }
                    }
                    if (typeof mantis !== 'undefined') {
                        setTimeout(function() {
                            mantis.push(['display', 'refresh']);
                        }, 300);
                    }
                }

                haptic('heavy');

                // Add phase transition animation
                const timerDisplay = document.querySelector('.timer-display');
                if (timerDisplay) {
                    timerDisplay.classList.add('phase-transition', 'vapor-effect');
                    setTimeout(() => {
                        timerDisplay.classList.remove('phase-transition', 'vapor-effect');
                    }, 1500);
                }

                if (!state.settings.isPremium) {
                    if (typeof mantis !== 'undefined') {
                        setTimeout(function() {
                            mantis.push(['display', 'refresh']);
                        }, 300);
                    }
                }

            } else {
                // Timer complete!
                completeTimer();
            }
        }
    }, 1000);
}

function updateTimerDisplay() {
    const mode = state.timer.mode === 'heat' ? 'Heat Your Banger' : 'Cool Down';
    const subtitle = state.timer.mode === 'heat' ? 'Perfection awaits...' : 'Almost ready...';

    const timerMode = document.getElementById('timer-mode');
    const timerCountdown = document.getElementById('timer-countdown');
    const timerSubtitle = document.getElementById('timer-subtitle');
    const timerProgress = document.getElementById('timer-progress');
    const timerCircle = document.getElementById('timer-circle');
    const pauseBtn = document.getElementById('pause-btn');

    if (timerMode) timerMode.textContent = mode;
    // Format time with leading zero to prevent shifting (always 2 digits)
    if (timerCountdown) timerCountdown.textContent = String(state.timer.timeLeft).padStart(2, '0');
    if (timerSubtitle) timerSubtitle.textContent = subtitle;

    // Update timer circle animation based on phase
    if (timerCircle) {
        timerCircle.classList.remove('heating', 'cooling');
        if (state.timer.isRunning && !state.timer.isPaused) {
            timerCircle.classList.add(state.timer.mode === 'heat' ? 'heating' : 'cooling');
        }
    }

    // Update progress bar
    if (timerProgress) {
        const elapsed = state.timer.mode === 'heat'
            ? state.timer.heatTime - state.timer.timeLeft
            : state.timer.heatTime + (state.timer.coolTime - state.timer.timeLeft);
        const progress = (elapsed / state.timer.totalTime) * 100;
        timerProgress.style.width = `${progress}%`;
    }

    // Update pause button
    if (pauseBtn) {
        if (state.timer.isPaused) {
            pauseBtn.innerHTML = '<i class="fas fa-play"></i><span>Resume</span>';
        } else {
            pauseBtn.innerHTML = '<i class="fas fa-pause"></i><span>Pause</span>';
        }
    }
}

function pauseTimer() {
    state.timer.isPaused = !state.timer.isPaused;
    updateTimerDisplay();
    haptic('light');
    console.log(`⏸️  Timer ${state.timer.isPaused ? 'paused' : 'resumed'}`);
}

function resetTimer() {
    state.timer.isRunning = false;
    state.timer.isPaused = false;
    if (state.timer.interval) clearInterval(state.timer.interval);

    // Remove timer animations
    const timerCircle = document.getElementById('timer-circle');
    if (timerCircle) {
        timerCircle.classList.remove('heating', 'cooling');
    }

    const videoAdReset = document.getElementById('cooldown-video-ad');
    if (videoAdReset) { videoAdReset.style.display = 'none'; videoAdReset.innerHTML = ''; }

    // Switch to home screen manually
    switchScreen('home');
    // showToast('⏹️ Timer reset', 'info'); // Removed - looks cheap
    haptic('light');
}

function completeTimer() {
    state.timer.isRunning = false;
    if (state.timer.interval) clearInterval(state.timer.interval);

    // Remove timer animations
    const timerCircle = document.getElementById('timer-circle');
    if (timerCircle) {
        timerCircle.classList.remove('heating', 'cooling');
    }

    const videoAdComplete = document.getElementById('cooldown-video-ad');
    if (videoAdComplete) { videoAdComplete.style.display = 'none'; videoAdComplete.innerHTML = ''; }

    // Show beautiful completion animation
    showCompletionAnimation();
    haptic('heavy');

    // Don't log session yet - will be done after session notes modal
    // Session will be logged in saveSessionNotes() or skipSessionNotes()

    console.log('✓ Timer Complete!');
}

function showCompletionAnimation() {
    // Play completion sound
    playSound('coolComplete');

    // Add timer complete animation to timer display
    const timerDisplay = document.querySelector('.timer-display');
    if (timerDisplay) {
        timerDisplay.classList.add('timer-complete');
        setTimeout(() => {
            timerDisplay.classList.remove('timer-complete');
        }, 1000);
    }

    // Create smoky haze overlay (hotbox effect)
    const overlay = document.createElement('div');
    overlay.className = 'completion-overlay smoke-haze';
    overlay.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: radial-gradient(circle at 50% 60%,
            rgba(152, 251, 152, 0.3) 0%,
            rgba(144, 238, 144, 0.25) 20%,
            rgba(143, 188, 143, 0.2) 40%,
            rgba(34, 139, 34, 0.15) 60%,
            rgba(0, 100, 0, 0.1) 80%,
            rgba(0, 0, 0, 0.95) 100%
        );
        z-index: 9999;
        display: flex;
        align-items: center;
        justify-content: center;
        animation: smokeIn 2s ease-out forwards;
        backdrop-filter: blur(3px);
    `;

    // Create rainbow "enjoy" text (Cheech & Chong theme) - cursive lowercase
    const text = document.createElement('div');
    text.className = 'completion-text rainbow-text';
    text.textContent = 'enjoy';
    text.style.cssText = `
        font-size: 5rem;
        font-weight: 400;
        font-family: 'Pacifico', cursive, 'Poppins', sans-serif;
        text-transform: lowercase;
        letter-spacing: 0.05em;
        background: linear-gradient(
            45deg,
            #FF0080 0%,
            #FF8C00 14%,
            #FFD700 28%,
            #00FF00 42%,
            #00CED1 57%,
            #1E90FF 71%,
            #8B00FF 85%,
            #FF0080 100%
        );
        background-size: 200% 200%;
        -webkit-background-clip: text;
        background-clip: text;
        -webkit-text-fill-color: transparent;
        animation: rainbowShift 3s ease-in-out infinite, textFadeIn 1.5s ease-out forwards;
        opacity: 0;
        filter: blur(20px);
        text-shadow: 0 0 30px rgba(255,255,255,0.5);
    `;

    overlay.appendChild(text);
    document.body.appendChild(overlay);

    // Remove overlay and show session notes modal after animation
    setTimeout(() => {
        overlay.style.opacity = '0';
        overlay.style.transition = 'opacity 1.5s ease';
        setTimeout(() => {
            overlay.remove();
            switchScreen('home');
            // Show session notes modal after a short delay (check if enabled)
            setTimeout(() => {
                // Session notes for premium OR trial users (first 5 sessions)
                const totalSessions = state.stats.totalSessions || 0;
                const isTrialPeriod = totalSessions <= 5 && !state.settings.isPremium;
                const hasPremiumAccess = state.settings.isPremium || isTrialPeriod;

                if (hasPremiumAccess && state.settings.sessionNotesEnabled !== false) {
                    showSessionNotesModal();
                } else {
                    // Skip session notes, just log the session
                    logSession();
                    checkAchievements();
                    updateFavoriteStrains();
                }
            }, 500);
        }, 1500);
    }, 3500);
}

// === SESSION LOGGING ===
function logSession(notes = null) {
    const session = {
        timestamp: Date.now(),
        date: new Date().toISOString(),
        material: state.settings.material,
        concentrate: state.settings.concentrate,
        heater: state.settings.heater,
        heatTime: state.timer.heatTime,
        coolTime: state.timer.coolTime,
        brand: notes?.brand || null,
        strain: notes?.strain || null,
        rating: notes?.rating || null
    };

    state.stats.sessions.push(session);
    state.stats.totalSessions++;

    // Update streak
    updateStreak();

    saveState();
    console.log('✓ Session Logged', session);
}

function updateStreak() {
    const today = new Date().toDateString();
    const lastSession = state.stats.lastSessionDate;

    if (!lastSession) {
        // First ever session
        state.stats.streak = 1;
    } else {
        const lastDate = new Date(lastSession).toDateString();
        const yesterday = new Date();
        yesterday.setDate(yesterday.getDate() - 1);
        const yesterdayStr = yesterday.toDateString();

        if (lastDate === today) {
            // Already dabbed today, streak continues
        } else if (lastDate === yesterdayStr) {
            // Dabbed yesterday, increment streak
            state.stats.streak++;
        } else {
            // Streak broken
            state.stats.streak = 1;
        }
    }

    state.stats.lastSessionDate = Date.now();
    saveState();
}

// === ACHIEVEMENTS ===
function checkAchievements() {
    ACHIEVEMENTS.forEach(achievement => {
        if (achievement.unlocked) return;

        let qualified = false;

        switch (achievement.type) {
            case 'sessions':
                // Total session count
                qualified = state.stats.totalSessions >= achievement.requirement;
                break;

            case 'streak':
                // Streak days
                qualified = state.stats.streak >= achievement.requirement;
                break;

            case 'material':
                // Count sessions with specific material
                const materialCount = state.stats.sessions.filter(s =>
                    s.material === achievement.material
                ).length;
                qualified = materialCount >= achievement.requirement;
                break;

            case 'concentrate':
                // Count sessions with specific concentrate
                const concentrateCount = state.stats.sessions.filter(s =>
                    s.concentrate === achievement.concentrate
                ).length;
                qualified = concentrateCount >= achievement.requirement;
                break;
        }

        if (qualified) {
            unlockAchievement(achievement);
        }
    });
}

function unlockAchievement(achievement) {
    achievement.unlocked = true;
    state.stats.achievements.push(achievement.id);

    // Unlock theme if this achievement has one
    if (achievement.unlocksTheme) {
        if (!state.stats.unlockedThemes) {
            state.stats.unlockedThemes = [];
        }
        if (!state.stats.unlockedThemes.includes(achievement.unlocksTheme)) {
            state.stats.unlockedThemes.push(achievement.unlocksTheme);
            // showToast(`🎨 New Theme Unlocked: ${achievement.unlocksTheme.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')}!`, 'success');
        }
    }

    saveState();

    // showToast(`🏆 Achievement: ${achievement.name}!`, 'success');
    playSound('achievement');
    haptic('heavy');
    console.log('✓ Achievement Unlocked:', achievement.name, achievement.unlocksTheme ? `(Theme: ${achievement.unlocksTheme})` : '');
}

// === STATS DISPLAY ===
function initializeStats() {
    updateStatsDisplay();
    console.log('✓ Stats Initialized');
}

function updateStatsDisplay() {
    // Update quick stats
    document.getElementById('total-sessions').textContent = state.stats.totalSessions;
    document.getElementById('streak-display').textContent = state.stats.streak;

    // Update achievements count
    const unlockedCount = ACHIEVEMENTS.filter(a => a.unlocked).length;
    const totalCount = ACHIEVEMENTS.length;
    const achievementsCountEl = document.getElementById('achievements-count');
    if (achievementsCountEl) {
        achievementsCountEl.textContent = unlockedCount;
    }
    const achievementsProgressEl = document.getElementById('achievements-progress');
    if (achievementsProgressEl) {
        achievementsProgressEl.textContent = `${unlockedCount}/${totalCount}`;
    }

    // Update achievements with modern cards
    const achievementList = document.getElementById('achievement-list');
    achievementList.innerHTML = '';

    ACHIEVEMENTS.forEach(ach => {
        const card = document.createElement('div');
        card.className = `achievement-card ${ach.unlocked ? 'unlocked' : 'locked'}`;
        card.setAttribute('data-achievement-id', ach.id);
        card.setAttribute('data-filter-state', ach.unlocked ? 'unlocked' : 'locked');

        const rewardText = ach.unlocksFeature || (ach.unlocksTheme ? `${ach.unlocksTheme.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')} Theme` : 'Bragging Rights');

        card.innerHTML = `
            <div class="achievement-icon-wrapper">
                ${ach.icon}
            </div>
            <div class="achievement-details">
                <div class="achievement-name">
                    ${ach.name}
                    ${ach.unlocked ? '<i class="fas fa-check-circle" style="color: var(--success); font-size: 0.9em;"></i>' : ''}
                </div>
                <div class="achievement-description">${ach.description}</div>
                <div class="achievement-reward">
                    <i class="fas fa-gift"></i>
                    <span>${rewardText}</span>
                </div>
            </div>
        `;

        achievementList.appendChild(card);
    });

    // Add filter functionality
    setupAchievementFilters();

    // Create activity chart
    createActivityChart();

    // Update session history
    updateSessionHistory();
}

// Achievement filter functionality
function setupAchievementFilters() {
    const filterTabs = document.querySelectorAll('.filter-tab');
    const achievementCards = document.querySelectorAll('.achievement-card');

    filterTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const filter = tab.dataset.filter;

            // Update active state
            filterTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            // Filter achievements
            achievementCards.forEach(card => {
                const filterState = card.dataset.filterState;
                if (filter === 'all') {
                    card.style.display = '';
                } else {
                    card.style.display = filterState === filter ? '' : 'none';
                }
            });
        });
    });
}

function updateSessionHistory() {
    const historyContainer = document.getElementById('session-history');
    if (!historyContainer) return;

    historyContainer.innerHTML = '';

    // Get last 10 sessions
    const recentSessions = state.stats.sessions.slice(-10).reverse();

    if (recentSessions.length === 0) {
        historyContainer.innerHTML = '<p class="text-secondary">No sessions yet. Complete your first dab to get started!</p>';
        return;
    }

    recentSessions.forEach(session => {
        const date = new Date(session.timestamp);
        const timeStr = date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
        const dateStr = date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

        // Build session notes display if available
        let notesHtml = '';
        if (session.brand || session.strain || session.rating) {
            const parts = [];
            if (session.brand) parts.push(`🏷️ ${session.brand}`);
            if (session.strain) parts.push(`🌿 ${session.strain}`);
            if (session.rating) parts.push(`⭐ ${session.rating}/10`);
            notesHtml = `
                <div style="font-size: var(--font-xs); color: var(--text-secondary); margin-top: var(--space-1); font-style: italic;">
                    ${parts.join(' • ')}
                </div>
            `;
        }

        const item = document.createElement('div');
        item.className = 'session-history-item';
        item.style.cssText = `
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: var(--space-3);
            background: rgba(255, 255, 255, 0.05);
            border-radius: var(--border-radius-md);
            margin-bottom: var(--space-2);
        `;

        item.innerHTML = `
            <div style="flex: 1;">
                <div style="font-weight: 600;">${session.material.charAt(0).toUpperCase() + session.material.slice(1)} • ${session.concentrate.charAt(0).toUpperCase() + session.concentrate.slice(1)}</div>
                <div style="font-size: var(--font-sm); color: var(--text-muted); margin-top: var(--space-1);">
                    ${session.heater.charAt(0).toUpperCase() + session.heater.slice(1)} • ${session.heatTime}s / ${session.coolTime}s
                </div>
                ${notesHtml}
            </div>
            <div style="text-align: right;">
                <div style="font-size: var(--font-sm); color: var(--text-secondary);">${timeStr}</div>
                <div style="font-size: var(--font-xs); color: var(--text-muted);">${dateStr}</div>
            </div>
        `;

        historyContainer.appendChild(item);
    });
}

function createActivityChart() {
    // Calculate week sessions
    const weekSessions = calculateWeekSessions();
    const weekElement = document.getElementById('week-sessions');
    if (weekElement) {
        weekElement.textContent = weekSessions;
    }

    // Update circular progress indicators
    updateCircularProgress();

    // Create pie charts
    createMaterialPieChart();
    createConcentratePieChart();
    // createHeaterPieChart(); // Removed - not applicable for dab rigs
    createTimePieChart();

    // Update premium stats
    updatePremiumStats();
}

function calculateWeekSessions() {
    const now = new Date();
    const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);

    return state.stats.sessions.filter(s => {
        const sessionDate = new Date(s.timestamp);
        return sessionDate >= weekAgo && sessionDate <= now;
    }).length;
}

function updateCircularProgress() {
    // Calculate percentages based on goals
    const sessionsPercent = Math.min((state.stats.totalSessions / 2000) * 100, 100);
    const streakPercent = Math.min((state.stats.streak / 100) * 100, 100);
    const achievementsPercent = (ACHIEVEMENTS.filter(a => a.unlocked).length / ACHIEVEMENTS.length) * 100;
    const weekPercent = Math.min((calculateWeekSessions() / 50) * 100, 100);

    // Update SVG circles
    updateCircle('sessions-circle', sessionsPercent);
    updateCircle('streak-circle', streakPercent);
    updateCircle('achievements-circle', achievementsPercent);
    updateCircle('week-circle', weekPercent);
}

function updateCircle(id, percent) {
    const circle = document.getElementById(id);
    if (!circle) return;

    const circumference = 2 * Math.PI * 24; // r=24 (updated for new size)
    const offset = circumference - (percent / 100) * circumference;
    circle.style.strokeDashoffset = offset;
}

function createMaterialPieChart() {
    const ctx = document.getElementById('material-pie-chart');
    if (!ctx) return;

    // Count material usage
    const materialCounts = {
        quartz: 0,
        titanium: 0,
        ceramic: 0
    };

    // Use actual session data only - no mock data
    const sessions = state.stats.sessions;

    sessions.forEach(s => {
        if (materialCounts[s.material] !== undefined) {
            materialCounts[s.material]++;
        }
    });

    if (state.charts.materialPie) {
        state.charts.materialPie.destroy();
    }

    state.charts.materialPie = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['Quartz', 'Titanium', 'Ceramic'],
            datasets: [{
                data: [materialCounts.quartz, materialCounts.titanium, materialCounts.ceramic],
                backgroundColor: [
                    'rgba(0, 245, 255, 0.8)',
                    'rgba(176, 38, 255, 0.8)',
                    'rgba(0, 230, 118, 0.8)'
                ],
                borderColor: [
                    'rgba(0, 245, 255, 1)',
                    'rgba(176, 38, 255, 1)',
                    'rgba(0, 230, 118, 1)'
                ],
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: '#FFFFFF',
                        font: {
                            size: 11
                        },
                        padding: 10,
                        generateLabels: function(chart) {
                            const data = chart.data;
                            if (data.labels.length && data.datasets.length) {
                                const dataset = data.datasets[0];
                                const total = dataset.data.reduce((a, b) => a + b, 0);
                                return data.labels.map((label, i) => {
                                    const value = dataset.data[i];
                                    const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : 0;
                                    return {
                                        text: `${label}: ${percentage}%`,
                                        fillStyle: dataset.backgroundColor[i],
                                        fontColor: '#FFFFFF',
                                        hidden: false,
                                        index: i
                                    };
                                });
                            }
                            return [];
                        }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const label = context.label || '';
                            const value = context.parsed;
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : 0;
                            return `${label}: ${value} (${percentage}%)`;
                        }
                    }
                }
            }
        }
    });
}

function createConcentratePieChart() {
    const ctx = document.getElementById('concentrate-pie-chart');
    if (!ctx) return;

    // Show ALL 10 concentrate types
    const allConcentrates = ['shatter', 'wax', 'rosin', 'live-resin', 'diamonds', 'sauce', 'budder', 'crumble', 'hash-rosin', 'distillate'];

    // Count all concentrates
    const concentrateCounts = {};
    allConcentrates.forEach(c => concentrateCounts[c] = 0); // Initialize all to 0

    // Use actual session data only - no mock data
    const sessions = state.stats.sessions;

    sessions.forEach(s => {
        if (concentrateCounts.hasOwnProperty(s.concentrate)) {
            concentrateCounts[s.concentrate]++;
        }
    });

    // Format labels (all concentrates)
    const labels = allConcentrates.map(name =>
        name.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
    );
    const data = allConcentrates.map(c => concentrateCounts[c]);

    if (state.charts.concentratePie) {
        state.charts.concentratePie.destroy();
    }

    state.charts.concentratePie = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: [
                    'rgba(255, 107, 53, 0.8)',   // Shatter - Orange
                    'rgba(255, 215, 0, 0.8)',    // Wax - Gold
                    'rgba(156, 39, 176, 0.8)',   // Rosin - Purple
                    'rgba(0, 230, 118, 0.8)',    // Live Resin - Green
                    'rgba(33, 150, 243, 0.8)',   // Diamonds - Blue
                    'rgba(233, 30, 99, 0.8)',    // Sauce - Pink
                    'rgba(255, 152, 0, 0.8)',    // Budder - Amber
                    'rgba(121, 85, 72, 0.8)',    // Crumble - Brown
                    'rgba(0, 191, 165, 0.8)',    // Hash Rosin - Teal
                    'rgba(103, 58, 183, 0.8)'    // Distillate - Indigo
                ],
                borderColor: [
                    'rgba(255, 107, 53, 1)',
                    'rgba(255, 215, 0, 1)',
                    'rgba(156, 39, 176, 1)',
                    'rgba(0, 230, 118, 1)',
                    'rgba(33, 150, 243, 1)',
                    'rgba(233, 30, 99, 1)',
                    'rgba(255, 152, 0, 1)',
                    'rgba(121, 85, 72, 1)',
                    'rgba(0, 191, 165, 1)',
                    'rgba(103, 58, 183, 1)'
                ],
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: '#FFFFFF',
                        font: {
                            size: 11
                        },
                        padding: 10,
                        generateLabels: function(chart) {
                            const data = chart.data;
                            if (data.labels.length && data.datasets.length) {
                                const dataset = data.datasets[0];
                                const total = dataset.data.reduce((a, b) => a + b, 0);
                                return data.labels.map((label, i) => {
                                    const value = dataset.data[i];
                                    const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : 0;
                                    return {
                                        text: `${label}: ${percentage}%`,
                                        fillStyle: dataset.backgroundColor[i],
                                        fontColor: '#FFFFFF',
                                        hidden: false,
                                        index: i
                                    };
                                });
                            }
                            return [];
                        }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const label = context.label || '';
                            const value = context.parsed;
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : 0;
                            return `${label}: ${value} (${percentage}%)`;
                        }
                    }
                }
            }
        }
    });
}

function createHeaterPieChart() {
    const ctx = document.getElementById('heater-pie-chart');
    if (!ctx) return;

    // Count heater usage (E-Nail, Torch, etc.)
    const heaterCounts = {
        'E-Nail': Math.floor(state.stats.totalSessions * 0.45),
        'Torch': Math.floor(state.stats.totalSessions * 0.35),
        'Peak/Puffco': Math.floor(state.stats.totalSessions * 0.15),
        'Other': Math.floor(state.stats.totalSessions * 0.05)
    };

    if (state.charts.heaterPie) {
        state.charts.heaterPie.destroy();
    }

    state.charts.heaterPie = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: Object.keys(heaterCounts),
            datasets: [{
                data: Object.values(heaterCounts),
                backgroundColor: [
                    'rgba(255, 87, 34, 0.8)',
                    'rgba(255, 167, 38, 0.8)',
                    'rgba(156, 39, 176, 0.8)',
                    'rgba(96, 125, 139, 0.8)'
                ],
                borderColor: [
                    'rgba(255, 87, 34, 1)',
                    'rgba(255, 167, 38, 1)',
                    'rgba(156, 39, 176, 1)',
                    'rgba(96, 125, 139, 1)'
                ],
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: '#FFFFFF',
                        font: {
                            size: 11
                        },
                        padding: 10,
                        generateLabels: function(chart) {
                            const data = chart.data;
                            if (data.labels.length && data.datasets.length) {
                                const dataset = data.datasets[0];
                                const total = dataset.data.reduce((a, b) => a + b, 0);
                                return data.labels.map((label, i) => {
                                    const value = dataset.data[i];
                                    const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : 0;
                                    return {
                                        text: `${label}: ${percentage}%`,
                                        fillStyle: dataset.backgroundColor[i],
                                        fontColor: '#FFFFFF',
                                        hidden: false,
                                        index: i
                                    };
                                });
                            }
                            return [];
                        }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const label = context.label || '';
                            const value = context.parsed;
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : 0;
                            return `${label}: ${value} (${percentage}%)`;
                        }
                    }
                }
            }
        }
    });
}

function createTimePieChart() {
    const ctx = document.getElementById('time-pie-chart');
    if (!ctx) return;

    // Calculate peak activity hours
    const timeRanges = {
        'Morning (6-11am)': 0,
        'Afternoon (12-5pm)': 0,
        'Evening (6-11pm)': 0,
        'Night (12-5am)': 0
    };

    state.stats.sessions.forEach(s => {
        const hour = new Date(s.timestamp).getHours();
        if (hour >= 6 && hour < 12) timeRanges['Morning (6-11am)']++;
        else if (hour >= 12 && hour < 18) timeRanges['Afternoon (12-5pm)']++;
        else if (hour >= 18 && hour < 24) timeRanges['Evening (6-11pm)']++;
        else timeRanges['Night (12-5am)']++;
    });

    if (state.charts.timePie) {
        state.charts.timePie.destroy();
    }

    state.charts.timePie = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: Object.keys(timeRanges),
            datasets: [{
                data: Object.values(timeRanges),
                backgroundColor: [
                    'rgba(255, 235, 59, 0.8)',
                    'rgba(255, 152, 0, 0.8)',
                    'rgba(156, 39, 176, 0.8)',
                    'rgba(63, 81, 181, 0.8)'
                ],
                borderColor: [
                    'rgba(255, 235, 59, 1)',
                    'rgba(255, 152, 0, 1)',
                    'rgba(156, 39, 176, 1)',
                    'rgba(63, 81, 181, 1)'
                ],
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: '#FFFFFF',
                        font: {
                            size: 11
                        },
                        padding: 10,
                        generateLabels: function(chart) {
                            const data = chart.data;
                            if (data.labels.length && data.datasets.length) {
                                const dataset = data.datasets[0];
                                const total = dataset.data.reduce((a, b) => a + b, 0);
                                return data.labels.map((label, i) => {
                                    const value = dataset.data[i];
                                    const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : 0;
                                    return {
                                        text: `${label}: ${percentage}%`,
                                        fillStyle: dataset.backgroundColor[i],
                                        fontColor: '#FFFFFF',
                                        hidden: false,
                                        index: i
                                    };
                                });
                            }
                            return [];
                        }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const label = context.label || '';
                            const value = context.parsed;
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : 0;
                            return `${label}: ${value} (${percentage}%)`;
                        }
                    }
                }
            }
        }
    });
}

// Update premium stats displays
function updatePremiumStats() {
    // Calculate month sessions (last 30 days)
    const now = new Date();
    const monthAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
    const monthSessions = state.stats.sessions.filter(s => {
        const sessionDate = new Date(s.timestamp);
        return sessionDate >= monthAgo && sessionDate <= now;
    }).length;

    const monthSessionsEl = document.getElementById('month-sessions');
    if (monthSessionsEl) {
        monthSessionsEl.textContent = monthSessions;
    }

    const avgPerDayEl = document.getElementById('avg-per-day');
    if (avgPerDayEl) {
        const avgPerDay = monthSessions > 0 ? (monthSessions / 30).toFixed(1) : '0.0';
        avgPerDayEl.textContent = avgPerDay;
    }

    // Personal records - use mock data in debug mode
    const bestStreakEl = document.getElementById('best-streak');
    if (bestStreakEl && state.settings.isPremium) {
        bestStreakEl.textContent = state.stats.bestStreak || state.stats.streak || '0';
    }

    const mostInDayEl = document.getElementById('most-in-day');
    if (mostInDayEl && state.settings.isPremium) {
        mostInDayEl.textContent = state.stats.mostInDay || '0';
    }

    const totalHoursEl = document.getElementById('total-hours');
    if (totalHoursEl && state.settings.isPremium) {
        // Calculate total hours (assuming ~3 minutes per session)
        const totalHours = Math.floor((state.stats.totalSessions * 3) / 60);
        totalHoursEl.textContent = totalHours > 0 ? totalHours : '0';
    }

    const avgDurationEl = document.getElementById('avg-duration');
    if (avgDurationEl && state.settings.isPremium) {
        avgDurationEl.textContent = state.stats.avgDuration || '0';
    }

    // Most used material/concentrate
    const mostUsedMaterialEl = document.getElementById('most-used-material');
    if (mostUsedMaterialEl) {
        const materialCounts = { quartz: 0, titanium: 0, ceramic: 0 };
        state.stats.sessions.forEach(s => {
            if (materialCounts[s.material] !== undefined) {
                materialCounts[s.material]++;
            }
        });
        const topMaterial = Object.entries(materialCounts).sort((a, b) => b[1] - a[1])[0];
        mostUsedMaterialEl.textContent = topMaterial ? topMaterial[0].charAt(0).toUpperCase() + topMaterial[0].slice(1) : 'Quartz';
    }

    const mostUsedConcentrateEl = document.getElementById('most-used-concentrate');
    if (mostUsedConcentrateEl) {
        const concentrateCounts = {};
        state.stats.sessions.forEach(s => {
            concentrateCounts[s.concentrate] = (concentrateCounts[s.concentrate] || 0) + 1;
        });
        const topConcentrate = Object.entries(concentrateCounts).sort((a, b) => b[1] - a[1])[0];
        if (topConcentrate) {
            mostUsedConcentrateEl.textContent = topConcentrate[0].split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
        } else {
            mostUsedConcentrateEl.textContent = 'Shatter';
        }
    }
}

// === UI UPDATES ===
function updateUI() {
    // Update streak display on home
    const streakCount = document.getElementById('streak-count');
    if (streakCount) {
        streakCount.textContent = `${state.stats.streak} Day Streak`;
    }
}

// === DATA EXPORT ===
function exportData() {
    const exportData = {
        app: 'DabFlow',
        version: '1.0.0',
        exportDate: new Date().toISOString(),
        totalSessions: state.stats.totalSessions,
        currentStreak: state.stats.streak,
        achievements: state.stats.achievements,
        sessions: state.stats.sessions,
        settings: state.settings
    };

    const dataStr = JSON.stringify(exportData, null, 2);
    const dataBlob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(dataBlob);

    const link = document.createElement('a');
    link.href = url;
    link.download = `dabflow-export-${Date.now()}.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    // showToast('📊 Data exported successfully!', 'success');
    haptic('medium');
    console.log('✓ Data Exported');
}

// === DATA IMPORT ===
function importData(file) {
    const reader = new FileReader();

    reader.onload = (e) => {
        try {
            const imported = JSON.parse(e.target.result);

            if (imported.app !== 'DabFlow') {
                // showToast('❌ Invalid export file', 'error');
                return;
            }

            // Merge data
            if (imported.sessions) {
                state.stats.sessions = [...state.stats.sessions, ...imported.sessions];
                state.stats.totalSessions += imported.sessions.length;
            }

            if (imported.achievements) {
                imported.achievements.forEach(achId => {
                    if (!state.stats.achievements.includes(achId)) {
                        state.stats.achievements.push(achId);
                    }
                });
            }

            saveState();
            updateStatsDisplay();
            // showToast('✅ Data imported successfully!', 'success');
            haptic('heavy');
            console.log('✓ Data Imported');
        } catch (error) {
            // showToast('❌ Error importing data', 'error');
            console.error('Import error:', error);
        }
    };

    reader.readAsText(file);
}

// === CLEAR DATA ===
function clearAllData() {
    if (confirm('⚠️ This will delete ALL your data. Are you sure?')) {
        if (confirm('🔴 FINAL WARNING: This cannot be undone!')) {
            localStorage.removeItem('dabflow_state');
            location.reload();
        }
    }
}

// === TOAST NOTIFICATIONS ===
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;

    document.body.appendChild(toast);

    setTimeout(() => {
        toast.remove();
    }, 3000);
}

// === INTERSTITIAL AD ===
function showInterstitialAd() {
    const overlay = document.createElement('div');
    overlay.id = 'interstitial-overlay';
    overlay.style.cssText = `
        position: fixed;
        top: 0; left: 0; right: 0; bottom: 0;
        background: #000;
        z-index: 99999;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        animation: fadeIn 0.3s ease;
    `;

    overlay.innerHTML = `
        <div style="width: 100%; max-width: 360px; display: flex; flex-direction: column; align-items: center;">
            <div style="width: 100%; display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; box-sizing: border-box;">
                <span style="color: rgba(255,255,255,0.5); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;">Ad</span>
                <span id="ad-total-countdown" style="color: rgba(255,255,255,0.5); font-size: 12px;">0:30</span>
            </div>
            <div id="video-ad-container" style="width: 300px; min-height: 250px; display: flex; align-items: center; justify-content: center;"></div>
            <div style="width: 100%; display: flex; justify-content: flex-end; align-items: center; padding: 8px 12px; box-sizing: border-box; min-height: 40px;">
                <span id="skip-waiting" style="color: rgba(255,255,255,0.5); font-size: 12px;">Skip in <span id="skip-timer">5</span>s</span>
                <button id="skip-ad-btn" style="display: none; background: rgba(255,255,255,0.15); border: 1px solid rgba(255,255,255,0.3); color: white; padding: 6px 16px; border-radius: 4px; font-size: 13px; cursor: pointer;">Skip Ad ›</button>
            </div>
            <p style="margin: 4px 0 0; font-size: 11px; color: rgba(255,255,255,0.3); text-align: center;">
                Remove ads — <a href="#" style="color: var(--theme-primary); text-decoration: none;" onclick="document.getElementById('interstitial-overlay').remove(); switchScreen('settings');">DabFlow Premium $4.99</a>
            </p>
        </div>
    `;

    document.body.appendChild(overlay);

    const adContainer = overlay.querySelector('#video-ad-container');
    const adFrame = document.createElement('iframe');
    adFrame.src = 'https://www.topcreativeformat.com/watchnew?key=7f3fef35ebe837c51793d861ec5d33ac';
    adFrame.width = '300';
    adFrame.height = '250';
    adFrame.frameBorder = '0';
    adFrame.scrolling = 'no';
    adContainer.appendChild(adFrame);

    const countdownEl = overlay.querySelector('#ad-total-countdown');
    const skipWaiting = overlay.querySelector('#skip-waiting');
    const skipTimerEl = overlay.querySelector('#skip-timer');
    const skipBtn = overlay.querySelector('#skip-ad-btn');

    const close = () => {
        overlay.style.opacity = '0';
        overlay.style.transition = 'opacity 0.3s ease';
        setTimeout(() => overlay.remove(), 300);
    };

    skipBtn.addEventListener('click', close);

    let total = 30;
    let skipLeft = 5;

    const timer = setInterval(() => {
        total--;
        const m = Math.floor(total / 60);
        const s = total % 60;
        countdownEl.textContent = m + ':' + String(s).padStart(2, '0');

        if (skipLeft > 0) {
            skipLeft--;
            skipTimerEl.textContent = skipLeft;
            if (skipLeft === 0) {
                skipWaiting.style.display = 'none';
                skipBtn.style.display = 'inline-block';
            }
        }

        if (total <= 0) {
            clearInterval(timer);
            close();
        }
    }, 1000);
}

// === HAPTIC FEEDBACK ===
function haptic(type = 'medium') {
    // Haptic feedback disabled - no-op function
    return;
}

// Add haptic feedback to ALL buttons
function initializeHapticFeedback() {
    // Haptic feedback is now handled explicitly in button click handlers
    // Removed automatic haptic on all clicks to prevent double-vibrations

    console.log('✓ Haptic Feedback Initialized');
}

// === SOUND EFFECTS ===
const sounds = {
    click: null,
    heatComplete: null,
    coolComplete: null,
    achievement: null
};

function initSounds() {
    try {
        // Placeholder for sound files - will be added later
        // sounds.click = new Audio('sounds/click.mp3');
        // sounds.heatComplete = new Audio('sounds/heat-complete.mp3');
        // sounds.coolComplete = new Audio('sounds/cool-complete.mp3');
        // sounds.achievement = new Audio('sounds/achievement.mp3');
        console.log('✓ Sounds initialized (placeholder)');
    } catch (e) {
        console.log('⚠️  Sounds not available');
    }
}

function playSound(soundName) {
    if (sounds[soundName] && state.settings.soundEnabled !== false) {
        try {
            sounds[soundName].currentTime = 0;
            sounds[soundName].play().catch(() => {
                // Silently fail if sound can't play
            });
        } catch (e) {
            // Silently fail
        }
    }
}

// === PREMIUM FEATURES ===
function handlePremiumPurchase() {
    haptic('medium');

    // Detect platform
    const isAndroidApp = window.Capacitor && window.Capacitor.getPlatform() === 'android';
    const isWeb = !isAndroidApp;

    // Show confirmation dialog
    const confirmed = confirm(
        '🎉 Upgrade to DabFlow Premium?\n\n' +
        '✓ Remove all ads\n' +
        '✓ Unlock all themes instantly\n' +
        '✓ Advanced statistics\n' +
        '✓ Custom timer presets\n' +
        '✓ Enhanced achievements\n\n' +
        'One-time purchase: $4.99\n\n' +
        'This will open the purchase flow.'
    );

    if (confirmed) {
        if (isWeb && window.simpleStripePayment) {
            // Use Stripe for web
            console.log('💳 Opening Stripe payment page...');
            window.simpleStripePayment.openPaymentPage();
        } else if (isAndroidApp && window.purchasePremiumAndroid) {
            // Use Google Play Billing for Android
            console.log('💳 Opening Google Play purchase...');
            window.purchasePremiumAndroid();
        } else {
            // Fallback: simulate for testing
            console.log('⚠️ Payment system not configured, simulating...');
            simulatePremiumPurchase();
        }
    }
}

function simulatePremiumPurchase() {
    // Show loading toast
    // showToast('💳 Processing purchase...', 'info');

    // Simulate purchase delay
    setTimeout(() => {
        // Activate premium
        activatePremium();

        // Show success
        // showToast('🎉 Welcome to Premium!', 'success');
        haptic('heavy');

        // Show celebration animation
        showPremiumUnlockAnimation();
    }, 1500);
}

function activatePremium() {
    // Set premium flag
    state.settings.isPremium = true;

    // Unlock all themes
    const allThemes = [
        'neon-cyber', 'emerald-green', 'sapphire-blue', 'amethyst-purple',
        'sunset-orange', 'bubblegum-pink', 'lava-flow', 'ice-crystal',
        'golden-amber', 'aurora-borealis', 'ocean-teal', 'crimson-red',
        'stoner-paradise', 'cheech-and-chong'
    ];

    if (!state.stats.unlockedThemes) {
        state.stats.unlockedThemes = [];
    }

    allThemes.forEach(theme => {
        if (!state.stats.unlockedThemes.includes(theme)) {
            state.stats.unlockedThemes.push(theme);
        }
    });

    // Save state
    saveState();

    // Update UI
    updatePremiumUI();

    console.log('✅ Premium activated!');
}

function updatePremiumUI() {
    const isPremium = state.settings.isPremium;

    // Trial period: First 5 sessions get premium analytics (but NOT themes)
    const totalSessions = state.stats.totalSessions || 0;
    const isTrialPeriod = totalSessions <= 5 && !isPremium;
    const hasPremiumAccess = isPremium || isTrialPeriod;

    // Update body class
    if (isPremium) {
        document.body.classList.add('is-premium');
    } else {
        document.body.classList.remove('is-premium');
    }

    // Update theme options (remove locks for premium ONLY - not trial)
    if (isPremium) {
        const themeOptions = document.querySelectorAll('.theme-option.locked');
        themeOptions.forEach(option => {
            option.classList.remove('locked');
            option.classList.add('unlocked', 'premium-unlocked');
        });
    }

    // Update Personal Records section lock
    const recordsLock = document.getElementById('records-premium-lock');
    const recordsGrid = document.getElementById('records-grid');
    const recordsLockIcon = document.getElementById('records-lock-icon');
    const statsOverlay = document.getElementById('stats-overlay');

    // Show trial message if in trial period
    if (isTrialPeriod && statsOverlay) {
        // Modify the overlay to show trial info instead of hiding completely
        const trialMessage = `<div style="position: absolute; top: 10px; right: 10px; background: linear-gradient(135deg, #FFD700, #FFA500); color: #000; padding: 8px 16px; border-radius: 20px; font-size: 12px; font-weight: 600; z-index: 101;">
            <i class="fas fa-gift"></i> FREE TRIAL: ${5 - totalSessions} sessions left
        </div>`;
        const trialBadge = document.getElementById('trial-badge');
        if (!trialBadge && statsOverlay.parentElement) {
            statsOverlay.parentElement.insertAdjacentHTML('beforeend', trialMessage.replace('trial-badge', 'id="trial-badge"'));
        }
    }

    if (hasPremiumAccess) {
        // Unlock Personal Records (for trial OR premium)
        if (recordsLock) recordsLock.style.display = 'none';
        if (recordsGrid) {
            recordsGrid.style.filter = 'none';
            recordsGrid.style.opacity = '1';
        }
        if (recordsLockIcon) recordsLockIcon.style.display = 'none';

        // Unlock Advanced Analytics section (for trial OR premium)
        if (statsOverlay) statsOverlay.style.display = 'none';

        // Unlock Session Notes feature (for trial OR premium)
        const sessionNotesLock = document.getElementById('session-notes-lock');
        const sessionNotesToggle = document.getElementById('session-notes-toggle');
        const sessionNotesSlider = document.querySelector('#session-notes-switch .slider');
        if (sessionNotesLock) sessionNotesLock.style.display = 'none';
        if (sessionNotesToggle) sessionNotesToggle.disabled = false;
        if (sessionNotesSlider) sessionNotesSlider.style.opacity = '1';

        // Hide ads ONLY for paid premium (not trial)
        if (isPremium) {
            const adContainers = document.querySelectorAll('.ad-container');
            adContainers.forEach(ad => ad.style.display = 'none');
        }
    } else {
        // Keep everything locked for free users (past trial)
        if (recordsLock) recordsLock.style.display = 'flex';
        if (recordsGrid) {
            recordsGrid.style.filter = 'blur(3px)';
            recordsGrid.style.opacity = '0.5';
        }
        if (recordsLockIcon) recordsLockIcon.style.display = 'inline';

        // Keep Advanced Analytics locked
        if (statsOverlay) statsOverlay.style.display = 'flex';

        // Keep Session Notes locked
        const sessionNotesLock = document.getElementById('session-notes-lock');
        const sessionNotesToggle = document.getElementById('session-notes-toggle');
        const sessionNotesSlider = document.querySelector('#session-notes-switch .slider');
        if (sessionNotesLock) sessionNotesLock.style.display = 'block';
        if (sessionNotesToggle) sessionNotesToggle.disabled = true;
        if (sessionNotesSlider) sessionNotesSlider.style.opacity = '0.5';

        // Remove trial badge if exists
        const trialBadge = document.getElementById('trial-badge');
        if (trialBadge) trialBadge.remove();
    }

    console.log(`✓ Premium UI updated (isPremium: ${isPremium})`);
}

// Show premium upgrade modal/redirect
function showPremiumUpgrade() {
    haptic('medium');

    // Show confirmation dialog
    const upgradeConfirm = confirm(
        '👑 DabFlow Premium - $4.99\\n\\n' +
        '✅ Ad-free experience\\n' +
        '✅ All 14 premium themes\\n' +
        '✅ Advanced analytics & records\\n' +
        '✅ Data export\\n\\n' +
        'Click OK to go to secure payment page!'
    );

    if (upgradeConfirm) {
        // Redirect to Stripe Payment Link
        window.location.href = 'https://buy.stripe.com/6oUdR97mB865gE89kF9Ve00';
    }
}

function restorePremiumPurchase() {
    haptic('light');

    // Show loading
    // showToast('🔄 Checking purchase status...', 'info');

    // Simulate restore check
    setTimeout(() => {
        // Check if already premium
        if (state.settings.isPremium) {
            // showToast('✓ Premium already active!', 'success');
        } else {
            // In production, this would check with Play Store / App Store
            // For now, check localStorage
            const savedPremium = localStorage.getItem('dabflow_premium');

            if (savedPremium === 'true') {
                activatePremium();
                // showToast('✅ Premium restored!', 'success');
            } else {
                // showToast('ℹ️ No purchase found', 'warning');
            }
        }
    }, 1000);
}

function showPremiumUnlockAnimation() {
    // Create celebration overlay
    const overlay = document.createElement('div');
    overlay.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0, 0, 0, 0.9);
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        z-index: 10000;
        animation: fadeIn 0.3s ease;
    `;

    overlay.innerHTML = `
        <div style="text-align: center; animation: premiumUnlock 0.6s cubic-bezier(0.68, -0.55, 0.265, 1.55);">
            <div style="font-size: 80px; margin-bottom: 20px;">👑</div>
            <h2 style="font-size: 32px; margin: 0; color: #FFD700;">Premium Unlocked!</h2>
            <p style="font-size: 18px; margin-top: 15px; opacity: 0.8;">All features are now available</p>
            <div style="margin-top: 30px;">
                <div style="font-size: 24px; margin-bottom: 10px;">✓ Ad-Free Experience</div>
                <div style="font-size: 24px; margin-bottom: 10px;">✓ All Themes Unlocked</div>
                <div style="font-size: 24px; margin-bottom: 10px;">✓ Advanced Statistics</div>
            </div>
            <button onclick="this.parentElement.parentElement.remove();" style="
                margin-top: 40px;
                padding: 15px 40px;
                background: linear-gradient(135deg, #FFD700, #FFA500);
                color: #000;
                border: none;
                border-radius: 25px;
                font-size: 18px;
                font-weight: 700;
                cursor: pointer;
            ">Let's Go! 🚀</button>
        </div>
    `;

    document.body.appendChild(overlay);

    // Auto-remove after 10 seconds
    setTimeout(() => {
        if (overlay.parentElement) {
            overlay.remove();
        }
    }, 10000);
}

// === SESSION NOTES MODAL ===
let currentSessionRating = 0;

function showSessionNotesModal() {
    const modal = document.getElementById('session-notes-modal');
    if (!modal) return;

    // Reset form
    document.getElementById('session-brand-input').value = '';
    document.getElementById('session-strain-input').value = '';
    currentSessionRating = 0;

    // Create star rating
    const ratingContainer = document.getElementById('session-rating-input');
    ratingContainer.innerHTML = '';
    for (let i = 1; i <= 10; i++) {
        const star = document.createElement('div');
        star.innerHTML = '<i class="fas fa-star"></i>';
        star.style.cssText = 'font-size: 1.5rem; color: rgba(255, 255, 255, 0.2); cursor: pointer; transition: all 0.2s ease;';
        star.onclick = () => setSessionRating(i);
        star.dataset.rating = i;
        ratingContainer.appendChild(star);
    }

    // Show modal
    modal.style.display = 'block';
    haptic('light');
}

function setSessionRating(rating) {
    currentSessionRating = rating;
    const stars = document.querySelectorAll('#session-rating-input > div');
    stars.forEach((star, index) => {
        if (index < rating) {
            star.style.color = '#FFD700';
            star.style.transform = 'scale(1.1)';
        } else {
            star.style.color = 'rgba(255, 255, 255, 0.2)';
            star.style.transform = 'scale(1)';
        }
    });
    haptic('light');
}

function saveSessionNotes() {
    const brand = document.getElementById('session-brand-input').value.trim();
    const strain = document.getElementById('session-strain-input').value.trim();
    const rating = currentSessionRating;

    const notes = {
        brand: brand || null,
        strain: strain || null,
        rating: rating || null
    };

    // Log session with notes
    logSession(notes);

    // Check achievements
    checkAchievements();

    // Update favorite strains display
    updateFavoriteStrains();

    // Close modal
    document.getElementById('session-notes-modal').style.display = 'none';
    haptic('medium');

    if (brand || strain || rating) {
        // showToast('📝 Session notes saved!', 'success');
    }
}

function skipSessionNotes() {
    // Log session without notes
    logSession();

    // Check achievements
    checkAchievements();

    // Update favorite strains display
    updateFavoriteStrains();

    // Close modal
    document.getElementById('session-notes-modal').style.display = 'none';
    haptic('light');
}

// Export sessions to CSV
function exportSessionsCSV() {
    if (state.stats.sessions.length === 0) {
        alert('No sessions to export!');
        return;
    }

    // CSV headers
    const headers = ['Date', 'Time', 'Material', 'Concentrate', 'Heater', 'Heat Time (s)', 'Cool Time (s)', 'Brand', 'Strain', 'Rating'];

    // Convert sessions to CSV rows
    const rows = state.stats.sessions.map(session => {
        const date = new Date(session.timestamp);
        const dateStr = date.toLocaleDateString('en-US');
        const timeStr = date.toLocaleTimeString('en-US');
        const material = session.material.charAt(0).toUpperCase() + session.material.slice(1);
        const concentrate = session.concentrate.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
        const heater = session.heater.charAt(0).toUpperCase() + session.heater.slice(1);

        return [
            dateStr,
            timeStr,
            material,
            concentrate,
            heater,
            session.heatTime,
            session.coolTime,
            session.brand || '',
            session.strain || '',
            session.rating || ''
        ].map(field => `"${field}"`).join(',');
    });

    // Combine headers and rows
    const csv = [headers.join(','), ...rows].join('\n');

    // Create download link
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `dabflow_sessions_${new Date().toISOString().split('T')[0]}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);

    haptic('medium');
    console.log(`✓ Exported ${state.stats.sessions.length} sessions to CSV`);
}

// Export all data (sessions + settings)
function exportAllData() {
    const data = {
        sessions: state.stats.sessions,
        settings: state.settings,
        stats: {
            totalSessions: state.stats.totalSessions,
            streak: state.stats.streak,
            lastSessionDate: state.stats.lastSessionDate,
            achievements: state.stats.achievements,
            unlockedThemes: state.stats.unlockedThemes
        },
        exportDate: new Date().toISOString()
    };

    const json = JSON.stringify(data, null, 2);
    const blob = new Blob([json], { type: 'application/json' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `dabflow_data_${new Date().toISOString().split('T')[0]}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);

    haptic('medium');
    console.log('✓ Exported all data to JSON');
}

// Temperature unit conversion
function convertTemperature(fahrenheit, toUnit) {
    if (toUnit === 'celsius') {
        return Math.round((fahrenheit - 32) * 5 / 9);
    }
    return fahrenheit;
}

function displayTemperature(fahrenheit) {
    const tempUnit = state.settings.tempUnit || 'fahrenheit';
    const temp = convertTemperature(fahrenheit, tempUnit);
    const unit = tempUnit === 'celsius' ? '°C' : '°F';
    return `${temp}${unit}`;
}

// Initialize temperature unit selector
function initTempUnitSelector() {
    const selector = document.getElementById('temp-unit-select');
    if (!selector) return;

    // Set current value
    selector.value = state.settings.tempUnit || 'fahrenheit';

    // Handle changes
    selector.addEventListener('change', () => {
        state.settings.tempUnit = selector.value;
        saveState();

        // Update all temperature displays
        const optimalTempEl = document.getElementById('session-optimal-temp');
        if (optimalTempEl && state.timer.optimalTemp) {
            optimalTempEl.textContent = displayTemperature(state.timer.optimalTemp);
        }

        haptic('light');
        console.log(`✓ Temperature unit changed to ${selector.value}`);
    });
}

// Update favorite strains display in stats
function updateFavoriteStrains() {
    const container = document.getElementById('favorite-strains-container');
    if (!container) return;

    // Get all sessions with notes
    const sessionsWithNotes = state.stats.sessions.filter(s => s.brand || s.strain || s.rating);

    if (sessionsWithNotes.length === 0) {
        container.innerHTML = `
            <div style="text-align: center; padding: var(--space-4); color: var(--text-secondary);">
                <i class="fas fa-leaf" style="font-size: 2rem; opacity: 0.3; margin-bottom: var(--space-2);"></i>
                <p style="font-size: var(--font-sm);">Add session notes to see your favorites</p>
            </div>
        `;
        return;
    }

    // Count strains and brands
    const strainCounts = {};
    const brandCounts = {};
    const strainRatings = {};

    sessionsWithNotes.forEach(session => {
        if (session.strain) {
            strainCounts[session.strain] = (strainCounts[session.strain] || 0) + 1;
            if (session.rating) {
                if (!strainRatings[session.strain]) strainRatings[session.strain] = [];
                strainRatings[session.strain].push(session.rating);
            }
        }
        if (session.brand) {
            brandCounts[session.brand] = (brandCounts[session.brand] || 0) + 1;
        }
    });

    // Get top 3 strains and brands
    const topStrains = Object.entries(strainCounts)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3);

    const topBrands = Object.entries(brandCounts)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3);

    // Build HTML
    let html = '<div style="display: flex; flex-direction: column; gap: var(--space-3);">';

    // Top Strains
    if (topStrains.length > 0) {
        topStrains.forEach(([strain, count], index) => {
            const avgRating = strainRatings[strain] ?
                (strainRatings[strain].reduce((a, b) => a + b, 0) / strainRatings[strain].length).toFixed(1) :
                null;
            const medal = index === 0 ? '🥇' : index === 1 ? '🥈' : '🥉';

            html += `
                <div style="background: rgba(255, 255, 255, 0.05); padding: var(--space-3); border-radius: var(--border-radius-md); display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <div style="font-size: var(--font-xs); color: var(--text-muted); text-transform: uppercase; margin-bottom: var(--space-1);">
                            ${medal} Strain
                        </div>
                        <div style="font-size: var(--font-lg); font-weight: 600; color: #00E676;">${strain}</div>
                        <div style="font-size: var(--font-xs); color: var(--text-secondary); margin-top: var(--space-1);">
                            ${count} sessions${avgRating ? ` • ⭐ ${avgRating}/10` : ''}
                        </div>
                    </div>
                </div>
            `;
        });
    }

    // Top Brands
    if (topBrands.length > 0) {
        topBrands.forEach(([brand, count], index) => {
            const medal = index === 0 ? '🥇' : index === 1 ? '🥈' : '🥉';

            html += `
                <div style="background: rgba(255, 255, 255, 0.05); padding: var(--space-3); border-radius: var(--border-radius-md); display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <div style="font-size: var(--font-xs); color: var(--text-muted); text-transform: uppercase; margin-bottom: var(--space-1);">
                            ${medal} Brand
                        </div>
                        <div style="font-size: var(--font-lg); font-weight: 600; color: #00F5FF;">${brand}</div>
                        <div style="font-size: var(--font-xs); color: var(--text-secondary); margin-top: var(--space-1);">
                            ${count} sessions
                        </div>
                    </div>
                </div>
            `;
        });
    }

    html += '</div>';
    container.innerHTML = html;
}

// === CSV EXPORT ===
function exportSessionsCSV() {
    if (!state.stats.sessions || state.stats.sessions.length === 0) {
        // showToast('📭 No sessions to export yet', 'warning');
        return;
    }

    // CSV Header
    let csv = 'Date,Time,Material,Concentrate,Heater,Heat Time (s),Cool Time (s),Total Time (s),Brand,Strain,Rating\n';

    // Add each session
    state.stats.sessions.forEach(session => {
        const date = new Date(session.timestamp || session.date);
        const dateStr = date.toLocaleDateString();
        const timeStr = date.toLocaleTimeString();
        const material = session.material || '';
        const concentrate = session.concentrate || '';
        const heater = session.heater || '';
        const heatTime = session.heatTime || '';
        const coolTime = session.coolTime || '';
        const totalTime = (session.heatTime || 0) + (session.coolTime || 0);
        const brand = session.brand || '';
        const strain = session.strain || '';
        const rating = session.rating || '';

        // Escape commas in text fields
        const escapedBrand = brand.includes(',') ? `"${brand}"` : brand;
        const escapedStrain = strain.includes(',') ? `"${strain}"` : strain;

        csv += `${dateStr},${timeStr},${material},${concentrate},${heater},${heatTime},${coolTime},${totalTime},${escapedBrand},${escapedStrain},${rating}\n`;
    });

    // Create blob and download
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');

    if (link.download !== undefined) {
        // Create download link
        const url = URL.createObjectURL(blob);
        const timestamp = new Date().toISOString().split('T')[0];
        link.setAttribute('href', url);
        link.setAttribute('download', `dabflow-sessions-${timestamp}.csv`);
        link.style.visibility = 'hidden';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);

        // showToast(`📊 Exported ${state.stats.sessions.length} sessions!`, 'success');
        haptic('medium');
    } else {
        // Fallback for browsers that don't support download attribute
        // showToast('❌ Export not supported on this device', 'error');
    }
}

// Make functions globally available
if (typeof window !== 'undefined') {
    window.showSessionNotesModal = showSessionNotesModal;
    window.saveSessionNotes = saveSessionNotes;
    window.skipSessionNotes = skipSessionNotes;
    window.setSessionRating = setSessionRating;
    window.updateFavoriteStrains = updateFavoriteStrains;
    window.exportSessionsCSV = exportSessionsCSV;
}

// Testing function - Remove in production or require secret code
function testActivatePremium() {
    activatePremium();
    showPremiumUnlockAnimation();
}

// Reset Premium for testing (accessible from UI)
function resetPremiumForTesting() {
    if (confirm('Reset Premium status? This will reload the app as a FREE user so you can test ads and payment flow.')) {
        // Clear all Premium data
        state.settings.isPremium = false;
        localStorage.removeItem('dabflow_premium');
        localStorage.removeItem('dabflow_settings');
        saveState();

        // Show confirmation and reload
        alert('✅ Premium reset! Reloading as FREE user...');
        location.reload();
    }
}

// Add to window for console testing
if (typeof window !== 'undefined') {
    window.testActivatePremium = testActivatePremium;
    window.resetPremiumForTesting = resetPremiumForTesting;
    window.deactivatePremium = function() {
        state.settings.isPremium = false;
        saveState();
        updatePremiumUI();
        // showToast('Premium deactivated (testing)', 'info');
        location.reload();
    };
}

// === MOCK DATA GENERATOR (For Review/Testing) ===
// Mock data generation function removed for production build
// All users will start with clean stats (totalSessions: 0, streak: 0, achievements: [])

// === SHARING FUNCTIONS ===

// Download link - will be updated to Play Store URL once published
const DOWNLOAD_LINK = 'https://github.com/twoskoops707/DabFlow/releases/latest';

// Initialize QR Code when settings screen is shown
function initializeQRCode() {
    const qrCodeElement = document.getElementById('qrcode');
    if (!qrCodeElement) return;

    // Clear any existing QR code
    qrCodeElement.innerHTML = '';

    // Generate QR code
    try {
        new QRCode(qrCodeElement, {
            text: DOWNLOAD_LINK,
            width: 200,
            height: 200,
            colorDark: '#000000',
            colorLight: '#ffffff',
            correctLevel: QRCode.CorrectLevel.H
        });
    } catch (error) {
        console.error('QR code generation failed:', error);
        qrCodeElement.innerHTML = '<p style="color: #666; font-size: 12px;">QR code unavailable</p>';
    }
}

// Send invite email
function sendInviteEmail() {
    const emailInput = document.getElementById('invite-email-input');
    const email = emailInput.value.trim();

    if (!email) {
        showToast('Please enter an email address', 'error');
        return;
    }

    // Validate email format
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
        showToast('Please enter a valid email address', 'error');
        return;
    }

    // Email subject and body
    const subject = encodeURIComponent('Check out DabFlow - Precision Concentrate Timer');
    const body = encodeURIComponent(
        `Hey!\n\n` +
        `I've been using DabFlow and thought you might like it too.\n\n` +
        `DabFlow is a precision timer app for concentrate vaporization with:\n` +
        `• Material-specific heat calculations (Quartz, Titanium, Ceramic)\n` +
        `• Optimal cool-down timing for best flavor\n` +
        `• 25 achievements to unlock\n` +
        `• 14 beautiful themes\n` +
        `• Advanced session tracking\n\n` +
        `Download it here: ${DOWNLOAD_LINK}\n\n` +
        `Enjoy! 🔥`
    );

    // Open email client with mailto link
    const mailtoLink = `mailto:${email}?subject=${subject}&body=${body}`;
    window.location.href = mailtoLink;

    // Clear input and show success message
    emailInput.value = '';
    showToast('Opening email client...', 'success');
    haptic('medium');
}

// Copy download link to clipboard
async function copyDownloadLink() {
    try {
        // Try modern clipboard API first
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(DOWNLOAD_LINK);
            showToast('Download link copied to clipboard!', 'success');
        } else {
            // Fallback for older browsers
            const textArea = document.createElement('textarea');
            textArea.value = DOWNLOAD_LINK;
            textArea.style.position = 'fixed';
            textArea.style.left = '-9999px';
            document.body.appendChild(textArea);
            textArea.select();
            document.execCommand('copy');
            document.body.removeChild(textArea);
            showToast('Download link copied!', 'success');
        }
        haptic('light');
    } catch (error) {
        console.error('Copy failed:', error);
        showToast('Failed to copy link', 'error');
    }
}

const screenZoneMap = {
    home:     ['zone-one', 'tester'],
    timer:    ['zone-two', 'zone-three', 'zone-four'],
    stats:    ['zone-five', 'zone-six', 'zone-seven'],
    glass:    ['zone-eight', 'zone-nine', 'zone-ten', 'zone-eleven'],
    settings: ['zone-twelve', 'zone-thirteen', 'zone-fourteen', 'zone-fifteen']
};

const originalSwitchScreen = switchScreen;
switchScreen = function(screenName) {
    originalSwitchScreen(screenName);

    if (screenName === 'settings') {
        setTimeout(initializeQRCode, 100);
    }

    const zones = screenZoneMap[screenName];
    if (zones && typeof mantis !== 'undefined') {
        setTimeout(function() {
            zones.forEach(function(zone) {
                mantis.push(['display', 'refresh', zone]);
            });
        }, 100);
    }
};

// Initialize sounds when app starts
initSounds();

// === ADD TO HOME SCREEN ===
let deferredPrompt;

// Capture the beforeinstallprompt event
window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    console.log('✓ Install prompt available');
});

// Handle Add to Home Screen button
document.addEventListener('DOMContentLoaded', () => {
    const addToHomeBtn = document.getElementById('add-to-home-btn');
    if (addToHomeBtn) {
        addToHomeBtn.addEventListener('click', async () => {
            haptic('medium');

            if (deferredPrompt) {
                // Show the install prompt
                deferredPrompt.prompt();
                const { outcome } = await deferredPrompt.userChoice;

                if (outcome === 'accepted') {
                    showToast('✅ App added! Long-press the icon for shortcuts', 'success');
                    console.log('User accepted the install prompt');
                } else {
                    showToast('ℹ️ Install cancelled', 'info');
                }
                deferredPrompt = null;
            } else {
                // Already installed or browser doesn't support
                showToast('💡 Use your browser menu: "Add to Home Screen" or "Install App"', 'info');
            }
        });
    }
});

// Mock data generation removed for production build
// Users will start with clean stats and achievements

// === WIDGET QUICK START ===
// Global function called by Android widget deep link
window.startQuickTimer = function() {
    console.log('🔥 Quick start triggered from widget!');

    // Function to safely start timer
    const safeStartTimer = () => {
        try {
            // Check if app is initialized
            if (typeof startTimer !== 'function') {
                console.error('❌ startTimer function not available yet');
                setTimeout(safeStartTimer, 200);
                return;
            }

            // Check if age verification passed
            const ageVerified = localStorage.getItem('dabflow_age_verified');
            if (ageVerified !== 'true') {
                console.log('ℹ️ Age not verified, showing app first');
                // Show app but don't start timer yet
                return;
            }

            console.log('✅ Starting timer from widget...');
            startTimer();
        } catch (error) {
            console.error('❌ Error starting timer from widget:', error);
        }
    };

    // Wait for DOM and app initialization
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            setTimeout(safeStartTimer, 300);
        });
    } else {
        // DOM is ready, wait a bit for app initialization
        setTimeout(safeStartTimer, 300);
    }
};

// === MUSEUM & GALLERY EXHIBIT FINDER ===

// Database of glass museums and galleries by region
const GLASS_MUSEUMS = {
    'Northeast': [
        { name: 'Corning Museum of Glass', city: 'Corning', state: 'NY', zip: '14830', url: 'https://www.cmog.org/', description: '35+ centuries of glass art, live demonstrations' },
        { name: 'Museum of Arts and Design', city: 'New York', state: 'NY', zip: '10019', url: 'https://madmuseum.org/', description: 'Contemporary craft and design, including glass' },
        { name: 'The Sandwich Glass Museum', city: 'Sandwich', state: 'MA', zip: '02563', url: 'https://sandwichglassmuseum.org/', description: 'Historic American pressed glass collection' }
    ],
    'Midwest': [
        { name: 'Toledo Museum of Art - Glass Pavilion', city: 'Toledo', state: 'OH', zip: '43604', url: 'https://www.toledomuseum.org/glass/', description: '5,000+ glass objects spanning 3,500 years' },
        { name: 'Bergstrom-Mahler Museum of Glass', city: 'Neenah', state: 'WI', zip: '54956', url: 'https://www.bergstrommahlermuseum.com/', description: 'World-renowned glass paperweight collection' },
        { name: 'Indianapolis Museum of Art', city: 'Indianapolis', state: 'IN', zip: '46208', url: 'https://discovernewfields.org/', description: 'Contemporary glass art exhibitions' }
    ],
    'West': [
        { name: 'Museum of Glass', city: 'Tacoma', state: 'WA', zip: '98402', url: 'https://www.museumofglass.org/', description: 'Contemporary glass art, Dale Chihuly exhibitions' },
        { name: 'Chihuly Garden and Glass', city: 'Seattle', state: 'WA', zip: '98109', url: 'https://www.chihulygardenandglass.com/', description: 'Stunning garden installations and galleries' },
        { name: 'Oakland Museum of California', city: 'Oakland', state: 'CA', zip: '94607', url: 'https://museumca.org/', description: 'California art including studio glass movement' }
    ],
    'South': [
        { name: 'Museum of Fine Arts Houston - Glass Collection', city: 'Houston', state: 'TX', zip: '77004', url: 'https://www.mfah.org/', description: 'European and American glass art' },
        { name: 'High Museum of Art', city: 'Atlanta', state: 'GA', zip: '30309', url: 'https://high.org/', description: 'Contemporary glass and decorative arts' }
    ]
};

function findNearbyExhibits() {
    haptic('light');

    const input = document.getElementById('exhibit-location-input');
    const resultsContainer = document.getElementById('nearby-exhibits-results');

    if (!input || !resultsContainer) return;

    const location = input.value.trim().toUpperCase();

    if (!location) {
        alert('Please enter a city, state, or zip code');
        return;
    }

    // Search all museums for matches
    let matches = [];

    for (const region in GLASS_MUSEUMS) {
        GLASS_MUSEUMS[region].forEach(museum => {
            // Check if input matches city, state, or zip
            if (museum.city.toUpperCase().includes(location) ||
                museum.state.toUpperCase().includes(location) ||
                museum.zip.includes(location) ||
                region.toUpperCase().includes(location)) {
                matches.push({ ...museum, region });
            }
        });
    }

    // If no exact matches, show all museums from a region
    if (matches.length === 0) {
        // Try to match region name
        for (const region in GLASS_MUSEUMS) {
            if (region.toUpperCase().includes(location)) {
                matches = GLASS_MUSEUMS[region].map(m => ({ ...m, region }));
                break;
            }
        }
    }

    // Display results
    if (matches.length > 0) {
        resultsContainer.style.display = 'block';
        resultsContainer.innerHTML = `
            <div style="padding: var(--space-3); background: rgba(78, 205, 196, 0.15); border-radius: var(--border-radius-md); margin-bottom: var(--space-3);">
                <div style="font-weight: 600; color: var(--theme-primary); margin-bottom: var(--space-2);">
                    📍 Found ${matches.length} museum${matches.length > 1 ? 's' : ''} near "${input.value}"
                </div>
            </div>
            ${matches.map(museum => `
                <a href="${museum.url}" target="_blank" rel="noopener" style="text-decoration: none; background: var(--bg-tertiary); padding: var(--space-4); border-radius: var(--border-radius-lg); border: 2px solid rgba(78, 205, 196, 0.4); display: block; margin-bottom: var(--space-3);">
                    <div style="display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-2);">
                        <div style="font-size: 2rem;">🎨</div>
                        <div style="flex: 1;">
                            <div style="font-weight: 700; color: var(--text-primary); font-size: var(--font-md);">${museum.name}</div>
                            <div style="font-size: var(--font-xs); color: var(--text-secondary);">${museum.city}, ${museum.state} ${museum.zip}</div>
                        </div>
                    </div>
                    <div style="font-size: var(--font-sm); color: var(--text-secondary);">
                        ${museum.description}
                    </div>
                </a>
            `).join('')}
        `;

        // Scroll to results
        resultsContainer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } else {
        resultsContainer.style.display = 'block';
        resultsContainer.innerHTML = `
            <div style="padding: var(--space-4); background: rgba(255, 140, 0, 0.1); border-radius: var(--border-radius-md); text-align: center;">
                <div style="font-size: 2rem; margin-bottom: var(--space-2);">🔍</div>
                <div style="font-weight: 600; color: var(--text-primary); margin-bottom: var(--space-2);">
                    No museums found for "${input.value}"
                </div>
                <div style="font-size: var(--font-sm); color: var(--text-secondary);">
                    Try searching by city (Seattle, Toledo), state (NY, WA, OH), or region (West, Northeast, Midwest, South)
                </div>
            </div>
        `;
    }
}

// Make function available globally
if (typeof window !== 'undefined') {
    window.findNearbyExhibits = findNearbyExhibits;
}

// Initialize age verification on page load (MUST BE AT END OF FILE)
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        const isVerified = initializeAgeGate();
        if (isVerified) {
            initializeApp();
        }
    });
} else {
    const isVerified = initializeAgeGate();
    if (isVerified) {
        initializeApp();
    }
}

console.log('✅ DabFlow Ready!');
