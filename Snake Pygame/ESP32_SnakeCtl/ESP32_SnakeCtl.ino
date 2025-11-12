#include "BluetoothSerial.h"

// Cria um objeto para o Bluetooth Serial
BluetoothSerial SerialBT;

void setup() {
  // Inicia a comunicação Serial (USB) com o PC
  // O Baud Rate (115200) DEVE ser o mesmo da sua config Python 
  Serial.begin(115200); 
  
  // Inicia o Bluetooth Serial e dá um nome ao seu ESP32
  // É este nome que vai aparecer no seu celular
  SerialBT.begin("Controle_Snake_Projeto"); 
  
  Serial.println("ESP32 pronto. Conecte ao app 'Controle_Snake_Projeto'");
}

void loop() {
  // Verifica se há dados chegando do Celular (Bluetooth)
  if (SerialBT.available()) {
    // Lê o dado que chegou do app
    char comando_do_app = SerialBT.read();
    
    // Envia o *mesmo* dado para o PC através do USB
    // USAMOS 'println' para que o 'ser.readline()'  do Python funcione!
    Serial.println(comando_do_app); 

    // (Opcional) Mostra no monitor serial o que está passando
    // Serial.print("Recebi do App: ");
    // Serial.println(comando_do_app);
  }
}