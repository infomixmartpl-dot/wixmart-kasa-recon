/// Тема додатку — кольори з WixMart brand tokens.
library;

import 'package:flutter/material.dart';

class AppColors {
  static const lime = Color(0xFFA6C211);     // акцент позитивний (збіги)
  static const sea = Color(0xFF1AAC7A);      // вторинний (готово/затверджено)
  static const orange = Color(0xFFFF6B35);   // CTA (запустити звірку, провести)
  static const danger = Color(0xFFD93025);   // пересорт/помилка
  static const warn = Color(0xFFE9A100);     // до проведення
  static const surface = Color(0xFFF7F8FA);  // фон карток
  static const text = Color(0xFF1A1F2C);
  static const muted = Color(0xFF6B7280);
}

ThemeData buildLightTheme() {
  final base = ThemeData.light(useMaterial3: true);
  return base.copyWith(
    colorScheme: ColorScheme.fromSeed(
      seedColor: AppColors.sea,
      primary: AppColors.sea,
      secondary: AppColors.orange,
      surface: AppColors.surface,
      error: AppColors.danger,
    ),
    scaffoldBackgroundColor: const Color(0xFFFAFAFA),
    appBarTheme: const AppBarTheme(
      backgroundColor: Colors.white,
      foregroundColor: AppColors.text,
      elevation: 0,
      surfaceTintColor: Colors.transparent,
      shape: Border(bottom: BorderSide(color: Color(0xFFE5E7EB))),
    ),
    cardTheme: CardThemeData(
      elevation: 0,
      surfaceTintColor: Colors.transparent,
      color: Colors.white,
      shape: RoundedRectangleBorder(
        side: const BorderSide(color: Color(0xFFE5E7EB)),
        borderRadius: BorderRadius.circular(12),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: AppColors.orange,
        foregroundColor: Colors.white,
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Colors.white,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: const BorderSide(color: Color(0xFFE5E7EB)),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: const BorderSide(color: Color(0xFFE5E7EB)),
      ),
    ),
  );
}
